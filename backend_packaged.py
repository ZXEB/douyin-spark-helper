import re, os, gzip, shutil, sys
from selenium import webdriver
from selenium.webdriver import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import SessionNotCreatedException
from selenium.webdriver.common.by import By
import schedule, requests
import time, uvicorn
from datetime import datetime
import json, base64
from fastapi import FastAPI, Header, Request, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
import threading, hashlib, secrets
import subprocess
import webbrowser

# 浏览器类型标记
BROWSER_TYPE = None  # 'chrome' 或 'edge'

if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
    INTERNAL_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    INTERNAL_DIR = APP_DIR

BASE_DIR = APP_DIR
RESOURCE_DIR = INTERNAL_DIR
CHROME_PROFILE_DIR = os.getenv('CHROME_PROFILE_DIR', os.path.join(BASE_DIR, 'chrome-profile'))

# 数据持久化文件路径
DATA_FILE = os.path.join(BASE_DIR, 'data.json')

# 数据持久化相关函数
def load_data():
    """从 JSON 文件加载数据"""
    default_data = {
        "tasks": [],
        "browser_type": "auto"
    }
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "tasks" not in data:
                    data["tasks"] = default_data["tasks"]
                if data.get("browser_type") not in ('auto', 'chrome', 'edge'):
                    data["browser_type"] = default_data["browser_type"]
                return data
        return default_data
    except Exception as e:
        print(f"加载数据文件失败: {e}")
        return default_data

def save_data(data):
    """保存数据到 JSON 文件"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存数据文件失败: {e}")
        return False


def get_browser_preference():
    data = load_data()
    browser_type = data.get('browser_type', 'auto')
    return browser_type if browser_type in ('auto', 'chrome', 'edge') else 'auto'


def set_browser_preference(browser_type):
    if browser_type not in ('auto', 'chrome', 'edge'):
        return False
    data = load_data()
    data['browser_type'] = browser_type
    return save_data(data)
DEFAULT_CHROME_BINARY = (
    r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    if os.name == 'nt'
    else '/opt/google/chrome/chrome'
)

DEFAULT_EDGE_BINARY = (
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    if os.name == 'nt'
    else '/usr/bin/microsoft-edge'
)

CHROMEDRIVER_PATH = os.getenv('CHROMEDRIVER_PATH', shutil.which('chromedriver') or '')
EDGEDRIVER_PATH = os.getenv('EDGEDRIVER_PATH', shutil.which('msedgedriver') or '')
CHROME_BINARY = os.getenv('CHROME_BINARY', DEFAULT_CHROME_BINARY)
EDGE_BINARY = os.getenv('EDGE_BINARY', DEFAULT_EDGE_BINARY)
off_ui = False

# 静态文件目录
STATIC_DIR = os.path.join(RESOURCE_DIR, 'frontend-dist')


def ensure_display_env():
    if os.name == 'nt':
        return None
    if os.getenv('DISPLAY'):
        return os.getenv('DISPLAY')
    for candidate in (':91', ':99', ':1'):
        if os.path.exists(f'/tmp/.X11-unix/X{candidate[1:]}'):
            os.environ['DISPLAY'] = candidate
            return candidate
    return None


def cleanup_stale_browser_processes():
    if os.name == 'nt':
        return
    pkill_path = shutil.which('pkill')
    if pkill_path:
        for pattern in (CHROMEDRIVER_PATH, CHROME_PROFILE_DIR):
            if pattern:
                subprocess.run([pkill_path, '-f', pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    for entry in ('SingletonCookie', 'SingletonLock', 'SingletonSocket', 'DevToolsActivePort'):
        target = os.path.join(CHROME_PROFILE_DIR, entry)
        try:
            if os.path.lexists(target):
                os.unlink(target)
        except Exception:
            pass


def build_chrome_options():
    options = ChromeOptions()
    if os.path.exists(CHROME_BINARY):
        options.binary_location = CHROME_BINARY
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_argument('log-level=3')
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.5481.177 Safari/537.36")
    options.add_experimental_option('excludeSwitches', ['enable-automation', 'useAutomationExtension'])
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--disable-web-security')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--no-sandbox')
    options.add_argument('--window-size=1400,3200')
    options.add_argument(f'--user-data-dir={CHROME_PROFILE_DIR}')
    options.add_argument('--remote-debugging-port=0')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--start-maximized')
    options.add_argument("--force-device-scale-factor=0.25")
    return options


def build_edge_options():
    options = EdgeOptions()
    if os.path.exists(EDGE_BINARY):
        options.binary_location = EDGE_BINARY
    options.add_argument('--disable-logging')
    options.add_argument('log-level=3')
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.5481.177 Safari/537.36 Edg/110.0.1587.69")
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--disable-web-security')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--no-sandbox')
    options.add_argument('--window-size=1400,3200')
    options.add_argument(f'--user-data-dir={CHROME_PROFILE_DIR}')
    options.add_argument('--remote-debugging-port=0')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--start-maximized')
    options.add_argument("--force-device-scale-factor=0.25")
    return options


def _try_init_chrome():
    """尝试使用 Chrome 初始化浏览器"""
    global BROWSER_TYPE
    options = build_chrome_options()
    if os.path.exists(CHROMEDRIVER_PATH):
        service = ChromeService(executable_path=CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    BROWSER_TYPE = 'chrome'
    return driver


def _try_init_edge():
    """尝试使用 Edge 初始化浏览器"""
    global BROWSER_TYPE
    options = build_edge_options()
    if os.path.exists(EDGEDRIVER_PATH):
        service = EdgeService(executable_path=EDGEDRIVER_PATH)
        driver = webdriver.Edge(service=service, options=options)
    else:
        driver = webdriver.Edge(options=options)
    BROWSER_TYPE = 'edge'
    return driver


def _body_text():
    try:
        return driver.find_element(By.TAG_NAME, 'body').text or ''
    except Exception:
        return ''


def _is_two_factor_page():
    text = _body_text()
    keywords = ['二次', '身份', '认证', '验证', '验证码', '扫脸', '手机号', '获取验证码', '安全']
    return any(keyword in text for keyword in keywords) and '扫码登录' not in text


def _find_first(by, selectors):
    last_error = None
    for selector in selectors:
        try:
            elements = driver.find_elements(by, selector)
            for element in elements:
                if element.is_displayed() and element.is_enabled():
                    return element
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise NoSuchElementException(str(selectors))


def _click_first_xpath(xpaths):
    element = _find_first(By.XPATH, xpaths)
    try:
        element.click()
    except Exception:
        driver.execute_script('arguments[0].click()', element)
    return element


def AiqingGongyu_text():
    req = requests.get('https://v2.xxapi.cn/api/aiqinggongyu')
    if req.status_code == 200:
        json_data = req.json()
        json_data = json_data['data']
        if json_data:
            return json_data
        else:
            return '暂无今日名言'
    else:
        return '暂无今日名言'


def Get_Cooke():
    driver.get('https://www.douyin.com/')
    for_OFF = True
    print('请登录抖音[且保持游览器为全屏!].....')
    while for_OFF:
        try:
            login_type_element = driver.find_element(By.XPATH,
                                                     '/html/body/div[2]/div[1]/div[4]/div[1]/div[1]/header/div/div/div[2]/div/pace-island/div/div[5]/div/div[1]/button/span/p')
        except NoSuchElementException:
            cooke = driver.get_cookies()
            print(f'Cooke获取成功,您的Cooke为 [请完整复制到cookies_list变量中]:\n{cooke}')
            driver.close()
            exit()


def format_time(time_str: str) -> str:
    if not time_str:
        return '22:00'
    time_str = time_str.replace('：', ':').strip()
    try:
        parts = time_str.split(':')
        if len(parts) != 2:
            print('时间格式错误，使用默认时间 22:00')
            return '22:00'
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            print('时间范围错误，使用默认时间 22:00')
            return '22:00'
        return f"{hour:02d}:{minute:02d}"
    except ValueError:
        print('时间解析错误，使用默认时间 22:00')
        return '22:00'


class TrueString:
    def __init__(self, is_bool, string):
        self.is_bool = is_bool
        self.string = string


class UserFriendsInfo:
    def __init__(self, username, avatar, fire):
        self.username = username
        self.avatar = avatar
        self.fire = fire


class Douyin:
    friends_xpath_list = {}

    def __init__(self, driver):
        self.driver = driver

    def PrintfFrinder(self):
        print(f'\n好友列表 共获取{len(self.friends_xpath_list)}位:\n------------------')
        for index, value in self.friends_xpath_list.items():
            print(index)
        print('------------------')

    def Updara_FrinderList(self):
        friends_xpath = '//div[@class="conversationConversationListwrapper"]/div/div/div'
        msg_main_list = driver.find_elements(By.XPATH, friends_xpath)
        temp_list = []
        for msg_len in range(1, len(msg_main_list) + 1):
            new_xpath = f'//div[@class="conversationConversationListwrapper"]/div/div[{msg_len + 1}]/div[1]/div[2]/div[1]/div[1]'
            avatar_xpath = f'//div[@class="conversationConversationListwrapper"]/div/div[{msg_len + 1}]/div[1]/div[1]/div/span/img'
            avatar_xpath2 = f'//div[@class="conversationConversationListwrapper"]/div/div[{msg_len + 1}]/div/div/img'
            fire_xpath = f'//div[@class="conversationConversationListwrapper"]/div/div[{msg_len + 1}]/div[1]/div[2]/div[1]/div[2]/div[1]/div/div'
            friends_get = driver.find_element(By.XPATH, value=new_xpath)
            friends_text = friends_get.text
            try:
                avatar_get = driver.find_element(By.XPATH, value=avatar_xpath)
                avatar = avatar_get.get_attribute('src')
            except:
                avatar_get = driver.find_element(By.XPATH, value=avatar_xpath2)
                avatar = avatar_get.get_attribute('src')
            self.friends_xpath_list[friends_text] = new_xpath
            try:
                fire_count = driver.find_element(By.XPATH, value=fire_xpath).text.strip()
            except:
                fire_count = ''
            temp_list.append(UserFriendsInfo(friends_text, avatar, fire_count))
        return temp_list

    def Send_Frinder(self, name: str, text: str):
        count = self.Updara_FrinderList()
        if count == 0:
            print("更新好友列表失败!")
        else:
            try:
                for index, value in self.friends_xpath_list.items():
                    if index == name:
                        friend_id = driver.find_element(By.XPATH, value=value)
                        friend_id.click()
                        time.sleep(1.5)
                        seng = driver.find_element(By.XPATH,
                                                   value='//div[@class="messageEditorimChatEditorContainer"]/div/div')
                        seng.send_keys(text)
                        seng.send_keys(Keys.ENTER)
                        return TrueString(True, None)
            except Exception as e:
                return TrueString(False, e)

    def Find_Friends(self, name: str):
        count = self.Updara_FrinderList()
        is_find = False
        if count == 0:
            return TrueString(False, '未初始化好友')
        try:
            for index, value in self.friends_xpath_list.items():
                if index == name:
                    is_find = True
            return TrueString(is_find, None)
        except Exception as e:
            return TrueString(False, e)

    def LoginInit(self):
        try:
            dle_user = driver.find_element(By.XPATH,
                                           value='//*[@id="douyin_login_comp_flat_panel"]/div/div[2]/div/div[4]/p')
            dle_user.click()
        except:
            pass


init = False
Login_is_bool = False
driver = None
douyin = None
scheduler_started = False
browser_lock = threading.Lock()
app = FastAPI()

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 处理 /api/ 前缀的中间件（兼容开发环境的 vite 代理）
class ApiPrefixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if request.url.path.startswith('/api/'):
            # 去掉 /api 前缀
            request.scope['path'] = request.url.path[4:]
            request.scope['raw_path'] = request.url.path[4:].encode()
        response = await call_next(request)
        return response


app.add_middleware(ApiPrefixMiddleware)

# 密码存储
_password = '123456'


def hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


# Token存储
_valid_tokens = set()
_last_login_ip = '无'


def generate_token() -> str:
    token = secrets.token_hex(32)
    _valid_tokens.add(token)
    return token


def verify_token(token: str) -> bool:
    return token in _valid_tokens


def remove_token(token: str):
    _valid_tokens.discard(token)


def require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith('Bearer '):
        return {'code': 401, 'data': '未授权'}
    token = authorization[7:]
    if not verify_token(token):
        return {'code': 401, 'data': '未授权'}
    return None


# 定时任务存储（内存中的 schedule 任务）
scheduled_tasks = {}

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

def start_scheduler():
    global scheduler_started
    if scheduler_started:
        return None
    scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
    scheduler_thread.start()
    scheduler_started = True
    return scheduler_thread

def restore_tasks_from_file():
    """从文件恢复定时任务"""
    global scheduled_tasks
    data = load_data()
    tasks = data.get("tasks", [])
    for task in tasks:
        task_id = task["task_id"]
        time_str = task["time"]
        name = task["name"]
        text = task.get("text")
        if douyin:
            msg = text if text else AiqingGongyu_text()
            job = schedule.every().day.at(time_str).do(douyin.Send_Frinder, name, msg)
            scheduled_tasks[task_id] = job
    print(f"已恢复 {len(tasks)} 个定时任务")

def save_tasks_to_file():
    """保存定时任务到文件"""
    data = load_data()
    tasks = []
    for task_id, job in scheduled_tasks.items():
        parts = task_id.split('_', 1)
        if len(parts) == 2:
            time_str, name = parts
            tasks.append({
                "task_id": task_id,
                "time": time_str,
                "name": name,
                "text": None,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    data["tasks"] = tasks
    save_data(data)


def _reset_browser_state():
    global init, Login_is_bool, driver, douyin
    old_driver = driver
    driver = None
    douyin = None
    init = False
    Login_is_bool = False
    if old_driver is not None:
        try:
            old_driver.quit()
        except Exception:
            pass


def _driver_alive():
    if driver is None:
        return False
    try:
        driver.execute_script('return document.readyState')
        return True
    except Exception:
        return False


def _detect_logged_in_state():
    if driver is None:
        return False
    try:
        login_panel = driver.find_elements(By.XPATH, '//*[@id="douyin_login_comp_flat_panel"]/picture')
        if login_panel:
            return False
    except Exception:
        pass

    xpaths = [
        '//div[contains(@class, "conversationConversationListwrapper")]',
        '//div[contains(@data-e2e, "im-list")]',
        '//div[contains(@class, "im-container")]',
    ]
    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            if any(element.is_displayed() for element in elements):
                return True
        except Exception:
            continue

    try:
        return '/chat' in (driver.current_url or '') and len(driver.get_cookies()) > 0
    except Exception:
        return False


def ensure_browser_ready():
    global init, driver, douyin, Login_is_bool
    with browser_lock:
        print('开始初始化浏览器...')
        browser_pref = get_browser_preference()
        if init and _driver_alive():
            if browser_pref != 'auto' and BROWSER_TYPE != browser_pref:
                print(f'浏览器类型不匹配 (当前: {BROWSER_TYPE}, 偏好: {browser_pref})，重置浏览器')
                _reset_browser_state()
            else:
                print('浏览器已初始化，复用现有会话')
                return None
        if init and not _driver_alive():
            print('检测到旧浏览器会话失效，准备重置')
            _reset_browser_state()
        try:
            if os.name != 'nt':
                display_value = ensure_display_env()
                if not display_value:
                    return {'code': 500, 'data': '初始化失败: 未找到可用的 DISPLAY/Xvfb 环境'}
                cleanup_stale_browser_processes()
            
            # 根据用户偏好选择浏览器
            print(f'浏览器偏好设置: {browser_pref}')
            
            if browser_pref == 'edge':
                try:
                    print('尝试启动 Edge...')
                    driver = _try_init_edge()
                    print("使用 Edge 浏览器")
                except Exception as edge_err:
                    print(f"Edge 初始化失败: {edge_err}")
                    return {'code': 500, 'data': f'Edge 浏览器初始化失败: {str(edge_err)}'}
            elif browser_pref == 'chrome':
                try:
                    print('尝试启动 Chrome...')
                    driver = _try_init_chrome()
                    print("使用 Chrome 浏览器")
                except Exception as chrome_err:
                    print(f"Chrome 初始化失败: {chrome_err}")
                    return {'code': 500, 'data': f'Chrome 浏览器初始化失败: {str(chrome_err)}'}
            else:
                # auto 模式：优先尝试 Chrome，失败则尝试 Edge
                try:
                    print('尝试启动 Chrome...')
                    driver = _try_init_chrome()
                    print("使用 Chrome 浏览器")
                except Exception as chrome_err:
                    print(f"Chrome 初始化失败: {chrome_err}")
                    try:
                        print('尝试启动 Edge...')
                        driver = _try_init_edge()
                        print("使用 Edge 浏览器")
                    except Exception as edge_err:
                        print(f"Edge 初始化失败: {edge_err}")
                        return {'code': 500, 'data': f'浏览器初始化失败，请确保已安装 Chrome 或 Edge 浏览器'}
            
            print('设置浏览器窗口大小...')
            driver.set_window_size(1400, 3200)
            print('打开抖音聊天页面...')
            driver.get('https://www.douyin.com/chat?isPopup=1 ')
            print('初始化 Douyin 控制器...')
            douyin = Douyin(driver)
            init = True
            Login_is_bool = _detect_logged_in_state()
            print(f'浏览器初始化完成，登录状态: {Login_is_bool}')
            start_scheduler()
            restore_tasks_from_file()
            return None
        except SessionNotCreatedException as e:
            _reset_browser_state()
            if "This version of Microsoft Edge WebDriver only supports" in str(e):
                return {'code': 400, 'data': '需要更新浏览器驱动!'}
            return {'code': 400, 'data': f'浏览器会话创建失败: {str(e)}'}
        except Exception as e:
            _reset_browser_state()
            print(f'浏览器初始化异常: {e}')
            return {'code': 500, 'data': f'初始化失败: {str(e)}'}


def require_browser_session():
    if init and _driver_alive():
        return None
    if init and not _driver_alive():
        _reset_browser_state()
        return {'code': 400, 'data': '浏览器会话已失效，请重新初始化浏览器'}
    return {'code': 400, 'data': '浏览器未初始化，请先初始化浏览器'}


start_time = datetime.now()


# 静态文件服务
@app.get('/')
async def serve_index():
    index_path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {'error': 'Frontend not found'}


@app.get('/assets/{path:path}')
async def serve_assets(path: str):
    file_path = os.path.join(STATIC_DIR, 'assets', path)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {'error': 'Asset not found'}


@app.get('/favicon.svg')
async def serve_favicon():
    file_path = os.path.join(STATIC_DIR, 'favicon.svg')
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {'error': 'Favicon not found'}


@app.get('/icons.svg')
async def serve_icons():
    file_path = os.path.join(STATIC_DIR, 'icons.svg')
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {'error': 'Icons not found'}


@app.get('/drops_drips_glass_141451_1280x720.jpg')
async def serve_bg():
    file_path = os.path.join(STATIC_DIR, 'drops_drips_glass_141451_1280x720.jpg')
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {'error': 'Background not found'}


# API 路由
@app.get('/Home')
def Home(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    return {'time': start_time}


@app.get('/Api/Init')
def Init(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err

    if init and _driver_alive():
        return {'code': 200, 'data': 'init Repeated!'}
    init_err = ensure_browser_ready()
    if init_err:
        return init_err
    return {'code': 200, 'data': 'success'}


@app.get('/Api/GetInit')
def GetInit(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    if init and not _driver_alive():
        _reset_browser_state()
    return {'code': 200, 'data': 'Yes' if init else 'No'}


@app.post('/Api/login')
def Login(cooke: str = Body(default=None), gzip_flag: bool = Body(default=False), authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    global Login_is_bool
    if cooke:
        try:
            decoded_bytes = base64.b64decode(cooke)
            if gzip_flag:
                try:
                    decoded_bytes = gzip.decompress(decoded_bytes)
                except Exception:
                    return {'code': '404',
                            'data': 'login-error-gzip decompress failed, check cookie format and gzip flag'}
            cookie_list = decoded_bytes.decode('utf-8')
            str = eval(base64.b64decode(cookie_list).decode('utf-8').replace('false', 'False').replace('true', 'True'))
            for cookie in str:
                driver.add_cookie(cookie)
        except Exception as e:
            return {'code': '404', 'data': f'login-error-cookie parse error: {str(e)}'}
        driver.refresh()
        try:
            login_type_element = driver.find_element(By.XPATH, '//*[@id="douyin_login_comp_flat_panel"]/picture')
            login_type = login_type_element.text
            return {'code': '404', 'data': 'login-error-cooker cant login'}
        except NoSuchElementException:
            Login_is_bool = True
            return {'code': '200', 'data': 'ok'}
    else:
        return {'code': '404', 'data': 'login-error-not cooker'}


@app.get('/Api/Pnglogin')
def PngLogin(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    global Login_is_bool
    time.sleep(1)
    if _detect_logged_in_state():
        Login_is_bool = True
        return {'code': '200', 'data': 'ok'}
    if _is_two_factor_page():
        Login_is_bool = False
        return {'code': 202, 'data': 'two_factor_required'}
    cooke = driver.get_cookies()
    if cooke:
        try:
            login_type_element = driver.find_element(By.XPATH, '//*[@id="douyin_login_comp_flat_panel"]/picture')
            login_type = login_type_element.text
            return {'code': '404', 'data': 'login-error-qr-not-confirmed'}
        except NoSuchElementException:
            Login_is_bool = True
            return {'code': '200', 'data': 'ok'}
    else:
        return {'code': '404', 'data': 'login-error-not cooker'}


@app.get('/Api/GetLogin')
def GetLogin(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    global Login_is_bool
    if init and not _driver_alive():
        _reset_browser_state()
    if init:
        Login_is_bool = _detect_logged_in_state()
    return {'code': 200, 'data': 'Yes' if Login_is_bool else 'No'}


@app.get('/Api/login/Init/GetLoginPng')
def GetLoginPng(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        Douyin.LoginInit(douyin)
        try:
            error = driver.find_element(By.XPATH, '//*[@id="animate_qrcode_container"]/div[2]/div/p[1]')
            img_element = driver.find_element(By.XPATH, '//*[@id="animate_qrcode_container"]/div[2]/img')
            img_element.click()
        except:
            pass
        img_element = driver.find_element(By.XPATH, '//*[@id="animate_qrcode_container"]/div[2]/img')
        login_src = img_element.get_attribute('src')
        try:
            is_rust = driver.find_element(By.XPATH, '//*[@id="animate_qrcode_container"]/div[2]/div')
            is_rust.click()
            time.sleep(5)
            img_element = driver.find_element(By.XPATH, '//*[@id="animate_qrcode_container"]/div[2]/img')
            login_src = img_element.get_attribute('src')
        except:
            pass
        if login_src:
            return {'code': 200, 'data': login_src}
        else:
            return {'code': 404, 'data': 'cant find LoginPng src attribute'}
    except NoSuchElementException:
        return {'code': 404, 'data': 'cant find img element'}


@app.get('/Api/login/Init/GetCooker')
def GetCooke(password: str = Query(None), authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    if not password or hash_pwd(password) != hash_pwd(_password):
        return {'code': 400, 'data': '密码错误'}
    if Login_is_bool:
        cooke = driver.get_cookies()
        cookie_json = json.dumps(cooke)
        cookie_base64 = base64.b64encode(cookie_json.encode('utf-8')).decode('utf-8')
        return {'code': 200, 'data': {'cooke': cookie_base64}}
    else:
        return {'code': 400, 'data': '未登录'}


@app.get('/Api/GetFriendsList')
def GetFrindesList(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        friends_list = douyin.Updara_FrinderList()
        if len(friends_list) == 0:
            return {'code': 404, 'data': '暂无好友或页面未加载'}
        dicts = {}
        for v in friends_list:
            dicts[v.username] = [v.avatar, v.fire]
        return {'code': 200, 'data': {'count': len(friends_list), 'list': dicts}}
    except Exception as e:
        return {'code': 404, 'data': str(e)}


@app.get('/Api/Send')
def Send(name: str, text: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    Douyin.Updara_FrinderList(douyin)
    out = Douyin.Send_Frinder(douyin, name, text)
    if out.is_bool:
        return {'code': 200, 'data': 'Send successfully'}
    else:
        return {'code': 404, 'data': out.string}


@app.get('/Api/GetUsername')
def GetUserInfo(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    if Login_is_bool:
        match = re.search(r'\\"nickname\\":\\"([^\\"]+)\\"', driver.page_source)
        if match:
            text = match.group(0)
            clean = text.replace('\\"', '"')
            data = json.loads('{' + clean + '}')
            return {'code': 200, 'data': data['nickname']}
        else:
            return {'code': 400, 'data': '已登录,但未获取到用户名'}
    else:
        return {'code': 400, 'data': '未登录'}


@app.get('/Api/GetScrlk')
def GetScrlk(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        driver.save_screenshot("temp.png")
        with open("temp.png", "rb") as f:
            img_data = base64.b64encode(f.read()).decode('utf-8')
        os.remove("temp.png")
        return {'code': 200, 'data': img_data}
    except Exception as e:
        return {'code': 400, 'data': f'截图错误:{e}'}


@app.get('/Api/DieLogin')
def DieLogin(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    driver.delete_all_cookies()
    driver.refresh()
    return {'code': 200, 'data': '已清除Cookie'}


@app.get('/Api/LoginPhone')
def authorization(areacode: str, phone: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        if not _is_two_factor_page():
            Douyin.LoginInit(douyin)

        try:
            areacode_value = _find_first(By.XPATH, [
                '//*[@id="douyin_login_comp_normal_input_id"]/div[1]/div/input',
                '//input[contains(@placeholder, "区号")]',
                '//input[contains(@placeholder, "国家")]',
            ])
            areacode_value.clear()
            areacode_value.send_keys(areacode.strip())
        except Exception:
            pass

        inp = _find_first(By.XPATH, [
            '//*[@id="normal-input"]',
            '//input[contains(@placeholder, "手机号")]',
            '//input[contains(@placeholder, "手机")]',
            '//input[@type="tel"]',
            '//input[@inputmode="tel"]',
        ])
        inp.clear()
        inp.send_keys(phone)

        button = _click_first_xpath([
            '//*[@id="douyin_login_comp_button_input_id"]',
            '//*[@id="douyin_login_comp_button_input_id"]/span',
            '//button[contains(., "验证码")]',
            '//*[contains(text(), "获取验证码")]',
            '//*[contains(text(), "发送验证码")]',
        ])
        time.sleep(2)
        if button.text and any(word in button.text for word in ['重新', '秒', 's', 'S']):
            return {'code': 200, 'data': 'verify code sent'}
        return {'code': 200, 'data': 'verify code sent'}
    except Exception as e:
        return {'code': 400, 'data': str(e)}


@app.get('/Api/LoginPhoneInput')
def authorizations(code: str, authorization: str = Header(None)):
    global Login_is_bool
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        inp = _find_first(By.XPATH, [
            '//*[@id="button-input"]',
            '//input[contains(@placeholder, "验证码")]',
            '//input[contains(@placeholder, "短信")]',
            '//input[@inputmode="numeric"]',
        ])
        inp.clear()
        inp.send_keys(code)

        _click_first_xpath([
            '//*[@id="douyin_login_comp_btn_id"]',
            '//button[contains(., "登录")]',
            '//button[contains(., "确认")]',
            '//button[contains(., "下一步")]',
        ])
        time.sleep(3)
        if _is_two_factor_page():
            return {'code': 400, 'data': 'secondary verification is still required'}
        try:
            driver.find_element(By.XPATH, '//*[@id="douyin_login_comp_flat_panel"]/picture')
            return {'code': 400, 'data': 'login failed'}
        except Exception:
            Login_is_bool = True
            return {'code': 200, 'data': 'login success'}
    except Exception as e:
        return {'code': 400, 'data': str(e)}


@app.get('/Api/LoginDebug')
def LoginDebug(authorization: str = Header(None)):
    global Login_is_bool
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    if Login_is_bool == False:
        Login_is_bool = True
        return {'code': 200, 'data': 'OK'}
    else:
        return {'code': 400, 'data': '已是登录状态,无需设定'}


@app.get('/Time/add')
def add_time(time: str, name: str, text: str = None, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    for task_id, job in scheduled_tasks.items():
        if task_id.endswith(f"_{name}"):
            return {'code': 400, 'data': f'好友 {name} 已有定时任务，请先删除或修改'}

    temp = douyin.Find_Friends(name)
    if temp.is_bool:
        play_time = format_time(time)
        msg = AiqingGongyu_text() if text == None else text
        job = schedule.every().day.at(play_time).do(douyin.Send_Frinder, name, msg)
        task_id = f"{play_time}_{name}"
        scheduled_tasks[task_id] = job
        
        # 持久化保存任务
        save_tasks_to_file()
        
        return {'code': 200, 'data': f'已添加定时任务: {play_time}', 'task_id': task_id}
    else:
        return {'code': 404, 'data': temp.string}


@app.get('/Time/del')
def del_time(task_id: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    if task_id in scheduled_tasks:
        job = scheduled_tasks[task_id]
        schedule.cancel_job(job)
        del scheduled_tasks[task_id]
        
        # 持久化保存
        save_tasks_to_file()
        
        return {'code': 200, 'data': f'已删除任务: {task_id}'}
    else:
        return {'code': 404, 'data': '任务ID不存在'}


@app.get('/Time/edit')
def edit_time(name: str, new_time: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    old_task_id = None
    for task_id, job in scheduled_tasks.items():
        if task_id.endswith(f"_{name}"):
            old_task_id = task_id
            break

    if not old_task_id:
        return {'code': 404, 'data': f'好友 {name} 没有定时任务'}

    old_job = scheduled_tasks[old_task_id]
    schedule.cancel_job(old_job)

    parts = old_task_id.split('_', 1)
    old_time = parts[0] if len(parts) == 2 else ""

    new_play_time = format_time(new_time)
    msg = AiqingGongyu_text()
    new_job = schedule.every().day.at(new_play_time).do(douyin.Send_Frinder, name, msg)

    new_task_id = f"{new_play_time}_{name}"
    scheduled_tasks[new_task_id] = new_job
    del scheduled_tasks[old_task_id]
    
    # 持久化保存
    save_tasks_to_file()

    return {
        'code': 200,
        'data': f'已将 {name} 的定时任务从 {old_time} 修改为 {new_play_time}',
        'old_time': old_time,
        'new_time': new_play_time,
        'task_id': new_task_id
    }


@app.get('/Time/getlist')
def get_time_list(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    tasks = []
    for task_id, job in scheduled_tasks.items():
        parts = task_id.split('_', 1)
        if len(parts) == 2:
            time_str, name = parts
            tasks.append({
                'task_id': task_id,
                'time': time_str,
                'name': name,
                'next_run': str(job.next_run) if job.next_run else None
            })
    return {'code': 200, 'data': {'count': len(tasks), 'tasks': tasks}}


@app.get('/Api/Login/Admin')
def admin_login(username: str, password: str, request: Request = None):
    global _last_login_ip
    if username == 'admin' and hash_pwd(password) == hash_pwd(_password):
        _last_login_ip = request.client.host if request else '127.0.0.1'
        token = generate_token()
        return {'code': 200, 'data': token}
    else:
        return {'code': 400, 'data': '登录失败'}


@app.get('/Api/GetLastLoginIP')
def get_last_login_ip(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    return {'code': 200, 'data': _last_login_ip}


@app.get('/Api/GetBrowserType')
def get_browser_type(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    return {'code': 200, 'data': get_browser_preference()}


@app.get('/Api/SetBrowserType')
def update_browser_type(browser_type: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    if browser_type not in ('auto', 'chrome', 'edge'):
        return {'code': 400, 'data': '不支持的浏览器类型'}
    if not set_browser_preference(browser_type):
        return {'code': 500, 'data': '保存浏览器配置失败'}
    _reset_browser_state()
    return {'code': 200, 'data': browser_type}


@app.get('/Api/logout')
def logout(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    token = authorization[7:]
    remove_token(token)
    return {'code': 200, 'data': '已退出登录'}


@app.get('/Api/ChangePassword')
def change_password(old_password: str, new_password: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    global _password
    if hash_pwd(old_password) != hash_pwd(_password):
        return {'code': 400, 'data': '原密码错误'}
    _password = new_password
    return {'code': 200, 'data': '密码修改成功'}


# 处理Vue Router的history模式
@app.get('/{path:path}')
async def serve_spa(path: str):
    # 如果是API路径，不处理
    if path.startswith('Api/') or path.startswith('Time/'):
        return {'error': 'Not found'}
    # 尝试返回静态文件
    file_path = os.path.join(STATIC_DIR, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    # 否则返回index.html（SPA路由）
    index_path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {'error': 'Frontend not found'}


def open_browser(port):
    """延迟打开浏览器"""
    time.sleep(2)
    webbrowser.open(f'http://localhost:{port}')


if __name__ == "__main__":
    port = int(os.getenv('PORT', '9844'))
    
    # 检查静态文件目录
    if not os.path.exists(STATIC_DIR):
        print(f"警告: 静态文件目录不存在: {STATIC_DIR}")
        print("请确保frontend-dist资源已正确打包")
    else:
        print(f"静态文件目录: {STATIC_DIR}")
    
    print(f"启动服务器: http://localhost:{port}")
    
    # 在后台线程中打开浏览器
    browser_thread = threading.Thread(target=open_browser, args=(port,), daemon=True)
    browser_thread.start()
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        reload=False
    )
