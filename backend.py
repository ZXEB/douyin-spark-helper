import re, os, gzip, shutil
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import schedule, requests
import time, uvicorn
from datetime import datetime
import json, base64
from fastapi import FastAPI, Header, Request, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
import threading, hashlib, secrets
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'frontend-dist')
if not os.path.exists(STATIC_DIR):
    STATIC_DIR = os.path.join(BASE_DIR, 'dist')
CHROME_PROFILE_DIR = os.getenv('CHROME_PROFILE_DIR', os.path.join(BASE_DIR, 'chrome-profile'))
off_ui = False


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
    for entry in ('SingletonCookie', 'SingletonLock', 'SingletonSocket', 'DevToolsActivePort'):
        target = os.path.join(CHROME_PROFILE_DIR, entry)
        try:
            if os.path.lexists(target):
                os.unlink(target)
        except Exception:
            pass


def build_browser_args():
    return [
        '--disable-blink-features=AutomationControlled',
        '--disable-gpu',
        '--disable-infobars',
        '--disable-notifications',
        '--disable-popup-blocking',
        '--disable-web-security',
        '--ignore-certificate-errors',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--force-device-scale-factor=1.0',
        '--lang=zh-CN,zh',
        '--mute-audio',
    ]


def _screenshot_b64():
    try:
        return base64.b64encode(page.screenshot()).decode('utf-8')
    except Exception:
        return ''


def _body_text():
    try:
        return page.locator('body').inner_text(timeout=3000)
    except Exception:
        return ''


def _is_two_factor_page():
    if page is None:
        return False
    try:
        has_verify_modal = page.evaluate("""() => {
            const inputs = document.querySelectorAll('input#normal-input, input#button-input, input[placeholder*="验证码"], input[placeholder*="手机"]');
            for (const i of inputs) {
                if (i.offsetParent !== null) return true;
            }
            const secElements = document.querySelectorAll('div[class*="secsdk"], div[class*="verify"], div[class*="captcha"], div[class*="account-verify"], div[class*="login-guide"]');
            for (const el of secElements) {
                if (el.offsetParent !== null && el.getBoundingClientRect().width > 50) return true;
            }
            const centerModals = Array.from(document.querySelectorAll('div')).filter(d => {
                const r = d.getBoundingClientRect();
                return r.width >= 250 && r.width <= 600 && r.height >= 180 && r.height <= 600 && Math.abs(r.left + r.width/2 - window.innerWidth/2) < 150;
            });
            if (centerModals.length > 0) {
                const modalText = centerModals[0].innerText || '';
                if (modalText.includes('验证') || modalText.includes('安全') || modalText.includes('确认') || modalText.includes('手机') || modalText.includes('密码') || centerModals[0].querySelectorAll('input').length > 0) {
                    return true;
                }
            }
            return false;
        }""")
        if has_verify_modal:
            return True

        text = _body_text()
        keywords = ['二次', '身份', '认证', '验证', '验证码', '扫脸', '手机号', '获取验证码', '安全']
        return any(keyword in text for keyword in keywords) and '扫码登录' not in text
    except Exception:
        return False


def _find_first_visible(selectors):
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                first = locator.first
                if first.is_visible():
                    return first
        except Exception:
            pass
    return None


def _click_first_xpath(xpaths):
    for xpath in xpaths:
        try:
            locator = page.locator(xpath)
            if locator.count() > 0 and locator.first.is_visible():
                locator.first.click(timeout=3000)
                return locator.first
        except Exception:
            try:
                locator.first.evaluate('el => el.click()')
                return locator.first
            except Exception:
                pass
    raise Exception(f'未找到可点击的元素: {xpaths}')


_http_session = requests.Session()
DEFAULT_QUOTES = [
    "生活明朗，万物可爱，火花不断！",
    "今天也是充满活力的一天！",
    "保持联系，岁月漫长，值得期待。",
    "保持热爱，奔赴山海。",
    "愿所有美好如期而至！",
    "每天都要保持好心情！"
]


def AiqingGongyu_text():
    try:
        req = _http_session.get('https://v2.xxapi.cn/api/aiqinggongyu', timeout=(2.0, 3.0))
        if req.status_code == 200:
            json_data = req.json()
            data = json_data.get('data')
            if data:
                return data
    except Exception as e:
        print(f"获取每日名言失败，使用随机默认语录: {e}")
    return secrets.choice(DEFAULT_QUOTES)


def format_time(time_str: str) -> str:
    if not time_str:
        return '22:00'
    time_str = time_str.replace('：', ':').strip()
    try:
        parts = time_str.split(':')
        if len(parts) != 2:
            return '22:00'
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return '22:00'
        return f"{hour:02d}:{minute:02d}"
    except ValueError:
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

    def __init__(self, page_ref):
        self.page = page_ref

    def PrintfFrinder(self):
        print(f'\n好友列表 共获取{len(self.friends_xpath_list)}位:\n------------------')
        for index, value in self.friends_xpath_list.items():
            print(index)
        print('------------------')

    def Updara_FrinderList(self):
        js_code = """() => {
        const list = [];
        const seen = new Set();
        
        // 使用抖音会话列表的精确 DOM 结构
        const items = document.querySelectorAll('div[data-e2e="conversation-item"]');
        for (const item of items) {
            // 提取好友名称（标题元素可能包含火花数与时间行，只取第一行）
            const titleEl = item.querySelector('[class*="ConversationItemtitle"], [class*="conversationConversationItemtitle"]');
            const name = titleEl ? titleEl.innerText.trim().split('\\n')[0].trim() : '';
            if (!name || seen.has(name)) continue;
            seen.add(name);

            // 提取头像
            const imgEl = item.querySelector('img');
            const avatar = imgEl ? (imgEl.src || '') : '';

            // 提取火花天数 - 从 commonStreakstreakContainer 中获取
            let fire = '';
            const streakEl = item.querySelector('[class*="commonStreakstreakContainer"], [class*="Streak"]');
            if (streakEl) {
                const streakText = streakEl.innerText.replace(/\\s+/g, '');
                if (streakText.includes('重燃中')) {
                    // 火花熄灭重燃期间显示的是进度（如 1/3）而非天数，保留原文
                    fire = streakText;
                } else {
                    const numMatch = streakText.match(/\\d+/);
                    if (numMatch) fire = numMatch[0];
                }
            }
            // 兜底：从标题旁标签提取，但只接受纯数字（可选"天"后缀），避免把日期/时间当成火花
            if (!fire) {
                const tagEl = item.querySelector('[class*="ConversationItemTagNextToTitle"]');
                if (tagEl) {
                    const tagMatch = tagEl.innerText.trim().match(/^(\\d{1,4})\\s*天?$/);
                    if (tagMatch) fire = tagMatch[1];
                }
            }

            list.push({ name, avatar, fire, index: list.length + 1 });
        }
        
        // 兜底策略：如果精确选择器没找到，使用宽松匹配
        if (list.length === 0) {
            const wrappers = document.querySelectorAll('div[class*="conversation"], div[class*="Conversation"], div[class*="chatList"], div[class*="chat-list"]');
            for (const w of wrappers) {
                const subItems = w.querySelectorAll(':scope > div, :scope > ul > li');
                for (let i = 0; i < subItems.length; i++) {
                    const subItem = subItems[i];
                    if (!subItem || subItem.children.length === 0) continue;
                    const rect = subItem.getBoundingClientRect();
                    if (rect.left > 350 || rect.height < 30) continue;
                    
                    const imgEl = subItem.querySelector('img');
                    const avatar = imgEl ? (imgEl.src || '') : '';
                    
                    const nameEl = subItem.querySelector('p, span[class*="name"], div[class*="name"]') ||
                                   Array.from(subItem.querySelectorAll('*')).find(el => {
                                       const t = el.innerText ? el.innerText.trim() : '';
                                       return t && el.children.length === 0 && t.length < 35 && !t.includes(':') && !/^\\d{1,2}:\\d{2}$/.test(t) && !/^\\d{2}\\/\\d{2}$/.test(t);
                                   });
                    const name = nameEl ? nameEl.innerText.trim() : '';
                    if (!name || seen.has(name)) continue;
                    seen.add(name);
                    
                    let fire = '';
                    const itemText = subItem.innerText || '';
                    const fireMatch = itemText.match(/🔥\\s*(\\d+)/) || itemText.match(/(\\d+)\\s*天/);
                    if (fireMatch) fire = fireMatch[1];
                    
                    list.push({ name, avatar, fire, index: list.length + 1 });
                }
            }
        }
        return list;
        }"""
        try:
            raw_list = self.page.evaluate(js_code) or []
        except Exception:
            raw_list = []

        temp_list = []
        self.friends_xpath_list = {}
        for item in raw_list:
            name = item.get('name', '')
            idx = item.get('index', 0)
            if name:
                self.friends_xpath_list[name] = str(idx)
                temp_list.append(UserFriendsInfo(name, item.get('avatar', ''), item.get('fire', '')))

        return temp_list

    def _open_conversation(self, name: str):
        """在会话列表中定位并打开指定好友的聊天窗口（调用方需持有 browser_lock）"""
        js_mark = """(target) => {
        const items = Array.from(document.querySelectorAll('div[data-e2e="conversation-item"]'));
        const titleOf = (it) => {
            const t = it.querySelector('[class*="ConversationItemtitle"]');
            return t ? t.innerText.trim().split('\\n')[0].trim() : '';
        };
        let item = items.find(it => titleOf(it) === target);
        if (!item) {
            item = items.find(it => {
                const n = titleOf(it);
                return n && n.length > 0 && (n.includes(target) || target.includes(n));
            });
        }
        if (!item) return { found: false, count: items.length };
        item.scrollIntoView({ block: 'center' });
        item.setAttribute('data-spark-target', '1');
        return { found: true, count: items.length, title: titleOf(item) };
        }"""
        js_reset = """() => {
        const containers = Array.from(document.querySelectorAll('div')).filter(d => {
            const s = getComputedStyle(d);
            return (s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                   d.scrollHeight > d.clientHeight + 10 &&
                   d.querySelector('div[data-e2e="conversation-item"]');
        });
        if (containers.length) containers[containers.length - 1].scrollTop = 0;
        return containers.length;
        }"""
        js_scroll = """() => {
        const containers = Array.from(document.querySelectorAll('div')).filter(d => {
            const s = getComputedStyle(d);
            return (s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                   d.scrollHeight > d.clientHeight + 10 &&
                   d.querySelector('div[data-e2e="conversation-item"]');
        });
        if (!containers.length) return { scrolled: false };
        const c = containers[containers.length - 1];
        const before = c.scrollTop;
        c.scrollTop = before + 420;
        return { scrolled: c.scrollTop > before };
        }"""

        # 会话列表在页面加载后异步渲染，先等待会话项出现
        for _ in range(25):
            try:
                count = self.page.evaluate("() => document.querySelectorAll('div[data-e2e=\"conversation-item\"]').length")
            except Exception:
                count = 0
            if count:
                break
            time.sleep(0.4)

        # 列表可能停留在上次滚动的位置，虚拟化会卸载顶部会话，先回到顶部
        try:
            self.page.evaluate(js_reset)
            time.sleep(0.4)
        except Exception:
            pass

        found = False
        for _ in range(20):
            try:
                r = self.page.evaluate(js_mark, name)
            except Exception:
                r = None
            if r and r.get('found'):
                found = True
                break
            try:
                s = self.page.evaluate(js_scroll)
            except Exception:
                s = None
            if not s or not s.get('scrolled'):
                break
            time.sleep(0.4)

        if not found:
            return TrueString(False, f"未在聊天列表中找到好友: {name}")

        loc = self.page.locator('div[data-spark-target="1"]').first
        clicked = False
        try:
            loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        for _ in range(2):
            try:
                loc.click(timeout=4000)
                clicked = True
                break
            except Exception:
                try:
                    loc.evaluate('el => el.click()')
                    clicked = True
                    break
                except Exception:
                    pass
        try:
            loc.evaluate('el => el.removeAttribute("data-spark-target")')
        except Exception:
            pass
        if not clicked:
            return TrueString(False, f"无法点击好友会话项: {name}")
        return TrueString(True, None)

    def _locate_editor(self):
        """轮询定位聊天输入框（调用方需持有 browser_lock）"""
        selectors = [
            'div[contenteditable="true"]',
            'div[role="textbox"]',
            'div[data-slate-editor="true"]',
            'div.zone-container div[contenteditable="true"]',
            'div[class*="Editor"] div[contenteditable="true"]',
            'div[class*="editor"] div[contenteditable="true"]',
            'div[class*="chat"] div[contenteditable="true"]',
            'div[class*="message"] div[contenteditable="true"]',
            'textarea[class*="editor"]',
            'textarea[placeholder*="发送"]',
            'textarea',
            'div.zone-container',
            'div[contenteditable]'
        ]
        for _ in range(25):
            time.sleep(0.2)
            for sel in selectors:
                try:
                    locator = self.page.locator(sel)
                    if locator.count() > 0:
                        el = locator.first
                        box = el.bounding_box()
                        if box and box.get('x', 0) >= 150 and box.get('width', 0) > 30 and box.get('height', 0) > 15:
                            return el
                except Exception:
                    pass
        try:
            locator = self.page.locator('div[contenteditable="true"], div[contenteditable]')
            if locator.count() > 0 and locator.first.is_visible():
                return locator.first
        except Exception:
            pass
        return None

    def Send_Frinder(self, name: str, text: str):
        with browser_lock:
            try:
                if '/chat' not in (self.page.url or ''):
                    self.page.goto('https://www.douyin.com/chat?isPopup=1', wait_until='domcontentloaded', timeout=30000)
                    time.sleep(2)

                open_res = self._open_conversation(name)
                if not open_res.is_bool:
                    return open_res

                editor = self._locate_editor()
                if not editor:
                    # 首次点击可能未真正打开会话，重试一次
                    self._open_conversation(name)
                    time.sleep(1)
                    editor = self._locate_editor()

                if not editor:
                    return TrueString(False, "未能定位到聊天输入框，请确认该好友聊天窗口已成功打开")

                try:
                    editor.click(timeout=2000)
                except Exception:
                    try:
                        editor.evaluate('el => { el.focus(); el.click(); }')
                    except Exception:
                        pass
                time.sleep(0.2)

                sent = False
                try:
                    editor.fill(text)
                    time.sleep(0.2)
                    editor.press('Enter')
                    sent = True
                except Exception:
                    pass

                if not sent:
                    js_send = """(el, text) => {
                    el.focus();
                    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                        el.value = text;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    } else {
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertText', false, text);
                        if (!el.innerText || !el.innerText.includes(text)) {
                            el.innerText = text;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    }
                    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keypress', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                    
                    const buttons = Array.from(document.querySelectorAll('button, div[role="button"], span[class*="send"], div[class*="send"]'));
                    for (const btn of buttons) {
                        const t = btn.innerText ? btn.innerText.trim() : '';
                        const rect = btn.getBoundingClientRect();
                        if ((t === '发送' || t.includes('发送')) && rect.left > 200) {
                            btn.click();
                            break;
                        }
                    }
                    }"""
                    editor.evaluate(js_send, text)

                return TrueString(True, None)
            except Exception as e:
                return TrueString(False, str(e))

    def Find_Friends(self, name: str):
        with browser_lock:
            try:
                friends = self.Updara_FrinderList()
                if not friends:
                    return TrueString(False, '未初始化好友或页面未加载')
                is_find = any(f.username == name for f in friends)
                return TrueString(is_find, None if is_find else f'未找到好友 {name}')
            except Exception as e:
                return TrueString(False, str(e))

    def LoginInit(self):
        try:
            locator = self.page.locator('//*[@id="douyin_login_comp_flat_panel"]/div/div[2]/div/div[4]/p')
            if locator.count() > 0:
                locator.first.evaluate('el => el.click()')
        except Exception:
            pass


init = False
Login_is_bool = False
pw = None
browser_context = None
page = None
douyin = None
scheduler_started = False
browser_lock = threading.Lock()
security_challenge_active = False
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApiPrefixMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if request.url.path.startswith('/api/'):
            request.scope['path'] = request.url.path[4:]
            request.scope['raw_path'] = request.url.path[4:].encode()
        response = await call_next(request)
        return response


app.add_middleware(ApiPrefixMiddleware)

_password = '123456'


def hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


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


scheduled_tasks = {}


def run_schedule():
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"定时调度执行异常: {e}")
        time.sleep(1)


def start_scheduler():
    global scheduler_started
    if scheduler_started:
        return None
    scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
    scheduler_thread.start()
    scheduler_started = True
    return scheduler_thread


def _reset_browser_state():
    global init, Login_is_bool, page, douyin, browser_context, pw, security_challenge_active
    old_context = browser_context
    old_pw = pw
    page = None
    douyin = None
    browser_context = None
    pw = None
    init = False
    Login_is_bool = False
    security_challenge_active = False
    if old_context is not None:
        try:
            old_context.close()
        except Exception:
            pass
    if old_pw is not None:
        try:
            old_pw.stop()
        except Exception:
            pass


def _page_alive():
    if page is None:
        return False
    try:
        page.evaluate('document.readyState')
        return True
    except Exception:
        return False


def _is_login_panel_visible():
    if page is None:
        return False
    try:
        visible = page.evaluate("""() => {
            const panel = document.getElementById('douyin_login_comp_flat_panel') || 
                          document.querySelector('div[class*="login-panel"], div[class*="loginContainer"], div[class*="login_comp"]');
            if (!panel) return false;
            const rect = panel.getBoundingClientRect();
            return panel.offsetParent !== null && rect.width > 0 && rect.height > 0 && window.getComputedStyle(panel).visibility !== 'hidden';
        }""")
        return bool(visible)
    except Exception:
        return False


def _detect_logged_in_state():
    if page is None:
        return False
    try:
        cookies = browser_context.cookies()
        cookie_dict = {c.get('name'): c.get('value') for c in cookies if 'name' in c and 'value' in c}
        has_auth_cookie = any(
            name in cookie_dict for name in ('sessionid', 'sessionid_ss', 'sid_tt', 'sid_guard', 'uid_tt', 'uid_tt_ss', 'passport_auth_status')
        ) or (cookie_dict.get('LOGIN_STATUS') == '1')
        
        dom_status = page.evaluate("""() => {
            const panel = document.getElementById('douyin_login_comp_flat_panel');
            const panelVisible = panel && panel.offsetParent !== null && panel.getBoundingClientRect().width > 0;
            const hasChatList = Array.from(document.querySelectorAll('img')).some(img => {
                const r = img.getBoundingClientRect();
                return r.left < 350 && r.width >= 20 && r.width <= 80;
            });
            const hasChatUrl = window.location.href.includes('/chat');
            return {
                panelVisible: Boolean(panelVisible),
                hasChatList: Boolean(hasChatList),
                hasChatUrl: Boolean(hasChatUrl)
            };
        }""")
        
        if dom_status and not dom_status.get('panelVisible') and (dom_status.get('hasChatList') or has_auth_cookie):
            return True
            
        if has_auth_cookie and not _is_login_panel_visible():
            return True
            
        return False
    except Exception:
        return False


def ensure_browser_ready():
    global init, page, douyin, Login_is_bool, browser_context, pw, security_challenge_active
    with browser_lock:
        if init and _page_alive():
            return None
        if init and not _page_alive():
            _reset_browser_state()
        try:
            if os.name != 'nt':
                display_value = ensure_display_env()
                if not display_value:
                    return {'code': 500, 'data': '初始化失败: 未找到可用的 DISPLAY/Xvfb 环境'}
                cleanup_stale_browser_processes()

            pw = sync_playwright().start()
            browser_context = pw.chromium.launch_persistent_context(
                user_data_dir=CHROME_PROFILE_DIR,
                headless=off_ui,
                args=build_browser_args(),
                viewport={'width': 1400, 'height': 900},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.5481.177 Safari/537.36',
                locale='zh-CN',
                ignore_https_errors=True,
            )
            page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
            page.goto('https://www.douyin.com/chat?isPopup=1', wait_until='domcontentloaded', timeout=30000)
            douyin = Douyin(page)
            init = True
            Login_is_bool = _detect_logged_in_state()
            start_scheduler()
            return None
        except Exception as e:
            _reset_browser_state()
            return {'code': 500, 'data': f'初始化失败: {str(e)}'}


def require_browser_session():
    if init and _page_alive():
        return None
    if init and not _page_alive():
        _reset_browser_state()
        return {'code': 400, 'data': '浏览器会话已失效，请重新初始化浏览器'}
    return {'code': 400, 'data': '浏览器未初始化，请先初始化浏览器'}


start_time = datetime.now()


@app.get('/Home')
def Home(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    return {'time': start_time}


@app.get('/Api/DebugDOM')
def debug_dom(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    if not page:
        return {'code': 400, 'data': 'page is None'}
    with browser_lock:
        js = """() => {
        const listItems = [];
        document.querySelectorAll('*').forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.left < 350 && rect.width > 100 && rect.height >= 40 && rect.height <= 100) {
                if (el.querySelector('img') && el.innerText && el.innerText.length > 0 && el.innerText.length < 100) {
                    listItems.push({
                        tag: el.tagName,
                        cls: typeof el.className === 'string' ? el.className : '',
                        text: el.innerText.replace(/\\n/g, ' | '),
                        html: el.outerHTML.substring(0, 300),
                        rect: { y: Math.round(rect.y), h: Math.round(rect.height) }
                    });
                }
            }
        });
        
        const editables = Array.from(document.querySelectorAll('div[contenteditable], textarea, input, div[role="textbox"]')).map(el => ({
            tag: el.tagName,
            cls: typeof el.className === 'string' ? el.className : '',
            role: el.getAttribute('role'),
            contenteditable: el.getAttribute('contenteditable'),
            placeholder: el.getAttribute('placeholder') || el.getAttribute('data-placeholder'),
            outerHTML: el.outerHTML.substring(0, 200)
        }));

        return {
            url: window.location.href,
            title: document.title,
            leftListCount: listItems.length,
            leftList: listItems.slice(0, 15),
            editables: editables
        };
        }"""
        data = page.evaluate(js)
        return {'code': 200, 'data': data}


@app.get('/Api/Init')
def Init(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    if init and _page_alive():
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
    if init and not _page_alive():
        _reset_browser_state()
    return {'code': 200, 'data': 'Yes' if init else 'No'}


def parse_cookie_payload(cookie_str: str) -> list:
    s = cookie_str.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()

    try:
        data = json.loads(s)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        if isinstance(data, str):
            s = data.strip()
    except Exception:
        pass

    try:
        b64_clean = re.sub(r'[^A-Za-z0-9+/=_-]', '', s)
        missing_pad = len(b64_clean) % 4
        if missing_pad in (2, 3):
            b64_clean += '=' * (4 - missing_pad)
        decoded = base64.b64decode(b64_clean).decode('utf-8', errors='ignore').strip()
        if (decoded.startswith('"') and decoded.endswith('"')) or (decoded.startswith("'") and decoded.endswith("'")):
            decoded = decoded[1:-1].strip()
        try:
            data = json.loads(decoded)
            if isinstance(data, (list, dict)):
                return data if isinstance(data, list) else [data]
        except Exception:
            import ast
            data = ast.literal_eval(decoded.replace('false', 'False').replace('true', 'True'))
            if isinstance(data, (list, dict)):
                return data if isinstance(data, list) else [data]
    except Exception:
        pass

    if '=' in s:
        cookies = []
        for pair in s.split(';'):
            if '=' in pair:
                name, val = pair.split('=', 1)
                name = name.strip()
                val = val.strip()
                if name:
                    cookies.append({'name': name, 'value': val, 'domain': '.douyin.com', 'path': '/'})
        if cookies:
            return cookies

    raise ValueError('无法识别的 Cookie 格式，支持 Base64、JSON 或 key=val 字符串')


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
                    return {'code': '404', 'data': 'login-error-gzip decompress failed, check cookie format and gzip flag'}
            raw_payload = decoded_bytes.decode('utf-8', errors='ignore')
            cookie_data = parse_cookie_payload(raw_payload)

            with browser_lock:
                pw_cookies = []
                for cookie in cookie_data:
                    if isinstance(cookie, dict) and 'name' in cookie and 'value' in cookie:
                        clean_cookie = {
                            'name': str(cookie['name']),
                            'value': str(cookie['value']),
                            'path': cookie.get('path', '/'),
                            'domain': cookie.get('domain', '.douyin.com')
                        }
                        pw_cookies.append(clean_cookie)
                if pw_cookies:
                    browser_context.add_cookies(pw_cookies)
                page.reload(wait_until='domcontentloaded', timeout=15000)
                time.sleep(1)
                if _detect_logged_in_state():
                    Login_is_bool = True
                    return {'code': '200', 'data': 'ok'}
                try:
                    locator = page.locator('//*[@id="douyin_login_comp_flat_panel"]/picture')
                    if locator.count() > 0:
                        return {'code': '404', 'data': 'login-error-cooker cant login'}
                except Exception:
                    pass
                Login_is_bool = True
                return {'code': '200', 'data': 'ok'}
        except Exception as e:
            return {'code': '404', 'data': f'login-error-cookie parse error: {str(e)}'}
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
    global Login_is_bool, security_challenge_active
    with browser_lock:
        screenshot_b64 = _screenshot_b64()

        if _is_two_factor_page():
            Login_is_bool = False
            security_challenge_active = True
            return {
                'code': 202,
                'data': 'two_factor_required',
                'screenshot': screenshot_b64,
                'message': '检测到抖音安全二次验证，请完成验证'
            }

        if _detect_logged_in_state():
            Login_is_bool = True
            security_challenge_active = False
            return {
                'code': '200',
                'data': 'ok',
                'screenshot': screenshot_b64,
                'message': '登录成功'
            }

        cookies = browser_context.cookies()
        cookie_dict = {c.get('name'): c.get('value') for c in cookies if 'name' in c}
        has_session = any(k in cookie_dict for k in ('sessionid', 'sessionid_ss', 'sid_tt', 'sid_guard', 'uid_tt')) or (cookie_dict.get('LOGIN_STATUS') == '1')
        
        if has_session:
            page.reload(wait_until='domcontentloaded', timeout=15000)
            time.sleep(1.2)
            screenshot_b64 = _screenshot_b64()
            if _detect_logged_in_state() or not _is_login_panel_visible():
                Login_is_bool = True
                security_challenge_active = False
                return {
                    'code': '200',
                    'data': 'ok',
                    'screenshot': screenshot_b64,
                    'message': '登录成功'
                }

        if _is_login_panel_visible():
            return {
                'code': '404',
                'data': 'login-error-qr-not-confirmed',
                'screenshot': screenshot_b64,
                'message': '等待手机端扫码并确认'
            }
        else:
            page.reload(wait_until='domcontentloaded', timeout=15000)
            time.sleep(1.0)
            screenshot_b64 = _screenshot_b64()
            if _detect_logged_in_state() or has_session:
                Login_is_bool = True
                security_challenge_active = False
                return {
                    'code': '200',
                    'data': 'ok',
                    'screenshot': screenshot_b64,
                    'message': '登录成功'
                }
            return {
                'code': '404',
                'data': 'login-error-qr-not-confirmed',
                'screenshot': screenshot_b64,
                'message': '等待手机端扫码确认'
            }


@app.get('/Api/GetLogin')
def GetLogin(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    global Login_is_bool
    if init and not _page_alive():
        _reset_browser_state()
    if init:
        with browser_lock:
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
        with browser_lock:
            Douyin.LoginInit(douyin)
            time.sleep(0.5)
            
            js_get_qr = """() => {
            const panel = document.getElementById('douyin_login_comp_flat_panel') || document.body;
            const imgs = Array.from(panel.querySelectorAll('img, canvas'));
            for (const el of imgs) {
                if (el.tagName === 'IMG' && el.src) {
                    const src = el.src;
                    const r = el.getBoundingClientRect();
                    if (src.includes('qrcode') || src.includes('data:image') || (r.width >= 80 && r.width <= 300 && r.height >= 80 && r.height <= 300)) {
                        return src;
                    }
                }
                if (el.tagName === 'CANVAS') {
                    const r = el.getBoundingClientRect();
                    if (r.width >= 80 && r.height >= 80) {
                        try { return el.toDataURL('image/png'); } catch(e) {}
                    }
                }
            }
            const q = document.querySelector('#animate_qrcode_container img, [data-e2e="qr-code"] img, div[class*="qrcode"] img');
            return q ? q.src : '';
            }"""
            login_src = ''
            # 二维码可能异步渲染，登录面板存在时重试几次
            for _ in range(4):
                login_src = page.evaluate(js_get_qr)
                if login_src or not _is_login_panel_visible():
                    break
                time.sleep(1.5)

            if not login_src:
                try:
                    locator = page.locator('//*[@id="animate_qrcode_container"]/div[2]/img')
                    if locator.count() > 0:
                        login_src = locator.first.get_attribute('src')
                except Exception:
                    pass

            if not login_src:
                try:
                    refresh_btn = page.locator('//*[@id="animate_qrcode_container"]/div[2]/div')
                    if refresh_btn.count() > 0:
                        refresh_btn.first.click(timeout=3000)
                        time.sleep(1)
                        login_src = page.evaluate(js_get_qr)
                except Exception:
                    pass

            panel_visible = _is_login_panel_visible()

        if login_src:
            return {'code': 200, 'data': login_src}
        if Login_is_bool or not panel_visible:
            return {'code': 400, 'data': '当前浏览器已登录抖音账号，没有可用的二维码。如需切换账号，请先点击「强制退出登录」再扫码'}
        return {'code': 404, 'data': 'cant find LoginPng src attribute'}
    except Exception as e:
        return {'code': 404, 'data': f'cant find img element: {str(e)}'}


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
        with browser_lock:
            cooke = browser_context.cookies()
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
        with browser_lock:
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
    out = douyin.Send_Frinder(name, text)
    if out.is_bool:
        return {'code': 200, 'data': 'Send successfully'}
    else:
        return {'code': 404, 'data': out.string}


@app.get('/Api/OpenChat')
def OpenChat(name: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    with browser_lock:
        if '/chat' not in (page.url or ''):
            page.goto('https://www.douyin.com/chat?isPopup=1', wait_until='domcontentloaded', timeout=30000)
            time.sleep(2)
        out = douyin._open_conversation(name)
        if out.is_bool:
            editor = douyin._locate_editor()
        else:
            editor = None
    if not out.is_bool:
        return {'code': 404, 'data': out.string}
    return {'code': 200, 'data': '聊天窗口已打开' if editor else '已点击会话，但未找到输入框'}


@app.get('/Api/LoginPhone')
def login_phone(areacode: str, phone: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        with browser_lock:
            js_send_code = """(args) => {
            const [phone, areacode] = args;
            
            const optionCards = Array.from(document.querySelectorAll('div, li, button')).filter(el => {
                const r = el.getBoundingClientRect();
                return r.width >= 180 && r.width <= 500 && r.height >= 35 && r.height <= 85;
            });
            for (const opt of optionCards) {
                const t = opt.innerText || '';
                if (t.includes('短信') || t.includes('验证码') || t.includes('手机')) {
                    opt.click();
                    break;
                }
            }
            
            const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"], [class*="protocol"], [class*="checkbox"], [class*="agree"]'));
            for (const cb of checkboxes) {
                if (cb.tagName === 'INPUT' && !cb.checked) {
                    cb.click();
                } else if (cb.tagName !== 'INPUT') {
                    cb.click();
                }
            }
            
            const phoneInputs = Array.from(document.querySelectorAll('input#normal-input, input[placeholder*="手机"], input[type="tel"], input[inputmode="tel"]'));
            for (const inp of phoneInputs) {
                inp.focus();
                inp.value = phone;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
                inp.dispatchEvent(new Event('blur', { bubbles: true }));
            }
            
            const btns = Array.from(document.querySelectorAll('button, span, div, a')).filter(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                const r = el.getBoundingClientRect();
                return (t === '获取验证码' || t === '发送验证码' || t.includes('获取验证码') || t.includes('重新发送')) && r.width > 20 && r.height > 15;
            });
            for (const btn of btns) {
                btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                btn.click();
                return true;
            }
            return false;
            }"""
            page.evaluate(js_send_code, [phone.strip(), areacode.strip()])
            time.sleep(1.5)

            try:
                inp = _find_first_visible([
                    '#normal-input',
                    'input[placeholder*="手机号"]',
                    'input[type="tel"]',
                ])
                if inp:
                    inp.fill(phone.strip())
                    _click_first_xpath([
                        '#douyin_login_comp_button_input_id',
                        'button:has-text("验证码")',
                        ':text("获取验证码")',
                    ])
            except Exception:
                pass

        screenshot = _screenshot_b64()
        return {'code': 200, 'data': 'verify code sent', 'screenshot': screenshot}
    except Exception as e:
        return {'code': 400, 'data': str(e)}


@app.get('/Api/LoginPhoneInput')
def login_phone_input(code: str, authorization: str = Header(None)):
    global Login_is_bool
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        with browser_lock:
            js_submit_code = """(code) => {
            const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"], [class*="protocol"], [class*="checkbox"], [class*="agree"]'));
            for (const cb of checkboxes) {
                if (cb.tagName === 'INPUT' && !cb.checked) {
                    cb.click();
                } else if (cb.tagName !== 'INPUT') {
                    cb.click();
                }
            }
            
            const codeInputs = Array.from(document.querySelectorAll('input#button-input, input[placeholder*="验证码"], input[placeholder*="短信"], input[inputmode="numeric"]'));
            for (const inp of codeInputs) {
                inp.focus();
                inp.value = code;
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                inp.dispatchEvent(new Event('change', { bubbles: true }));
            }
            
            const submitBtns = Array.from(document.querySelectorAll('button, div[role="button"], span')).filter(el => {
                const t = el.innerText ? el.innerText.trim() : '';
                const r = el.getBoundingClientRect();
                return (t === '登录' || t === '确认' || t === '下一步' || t.includes('立即登录')) && r.width > 40 && r.height > 20;
            });
            for (const btn of submitBtns) {
                btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                btn.click();
                return true;
            }
            return false;
            }"""
            page.evaluate(js_submit_code, code.strip())
            time.sleep(2.0)

            try:
                inp = _find_first_visible([
                    '#button-input',
                    'input[placeholder*="验证码"]',
                ])
                if inp:
                    inp.fill(code.strip())
                    _click_first_xpath([
                        '#douyin_login_comp_btn_id',
                        'button:has-text("登录")',
                        'button:has-text("确认")',
                    ])
            except Exception:
                pass
                
            time.sleep(1.5)
            
            if _detect_logged_in_state():
                Login_is_bool = True
                return {'code': 200, 'data': 'ok'}
            
            cookies = browser_context.cookies()
            cookie_dict = {c.get('name'): c.get('value') for c in cookies}
            if any(k in cookie_dict for k in ('sessionid', 'sessionid_ss', 'sid_tt', 'sid_guard', 'uid_tt')) or (cookie_dict.get('LOGIN_STATUS') == '1'):
                page.reload(wait_until='domcontentloaded', timeout=15000)
                time.sleep(1.5)
                if _detect_logged_in_state():
                    Login_is_bool = True
                    return {'code': 200, 'data': 'ok'}

            screenshot = _screenshot_b64()
            return {'code': 200, 'data': 'ok', 'screenshot': screenshot}
    except Exception as e:
        return {'code': 400, 'data': str(e)}


@app.get('/Api/GetUsername')
def GetUserInfo(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    if Login_is_bool:
        with browser_lock:
            page_src = page.content()
        match = re.search(r'\\"nickname\\":\\"([^\\"]+)\\"', page_src)
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
        with browser_lock:
            img_data = _screenshot_b64()
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
    with browser_lock:
        browser_context.clear_cookies()
        page.reload(wait_until='domcontentloaded', timeout=15000)
    return {'code': 200, 'data': '已清除Cookie'}


@app.get('/Api/LoginDebug')
def LoginDebug(authorization: str = Header(None)):
    global Login_is_bool
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    if not Login_is_bool:
        Login_is_bool = True
        return {'code': 200, 'data': 'OK'}
    else:
        return {'code': 400, 'data': '已是登录状态，无需设定'}


# ========== 手动控制浏览器（安全验证）==========

@app.get('/Api/SecurityStatus')
def security_status(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    global security_challenge_active
    with browser_lock:
        is_challenge = _is_two_factor_page()
        security_challenge_active = is_challenge
    return {'code': 200, 'data': {'active': is_challenge}}


@app.get('/Api/FocusBrowser')
def focus_browser(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    try:
        with browser_lock:
            page.bring_to_front()
        return {'code': 200, 'data': '浏览器窗口已置前'}
    except Exception as e:
        return {'code': 400, 'data': f'无法置前浏览器: {str(e)}'}


@app.get('/Api/ResumeAutomation')
def resume_automation(authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err
    browser_err = require_browser_session()
    if browser_err:
        return browser_err
    global Login_is_bool, security_challenge_active
    with browser_lock:
        security_challenge_active = False
        Login_is_bool = _detect_logged_in_state()
    return {'code': 200, 'data': 'ok', 'logged_in': Login_is_bool}


# ========== 定时任务 ==========

def make_schedule_job(name: str, custom_text: str = None):
    def _job_callback():
        text_to_send = custom_text if custom_text else AiqingGongyu_text()
        return douyin.Send_Frinder(name, text_to_send)
    return _job_callback


@app.get('/Time/add')
def add_time(time: str, name: str, text: str = None, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err

    for task_id in scheduled_tasks.keys():
        if task_id.endswith(f"_{name}"):
            return {'code': 400, 'data': f'好友 {name} 已有定时任务，请先删除或修改'}

    temp = douyin.Find_Friends(name)
    if temp.is_bool:
        play_time = format_time(time)
        job = schedule.every().day.at(play_time).do(make_schedule_job(name, text))
        task_id = f"{play_time}_{name}"
        scheduled_tasks[task_id] = job
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
        return {'code': 200, 'data': f'已删除任务: {task_id}'}
    else:
        return {'code': 404, 'data': '任务ID不存在'}


@app.get('/Time/edit')
def edit_time(name: str, new_time: str, authorization: str = Header(None)):
    auth_err = require_auth(authorization)
    if auth_err:
        return auth_err

    old_task_id = None
    for task_id in scheduled_tasks.keys():
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
    new_job = schedule.every().day.at(new_play_time).do(make_schedule_job(name, None))

    new_task_id = f"{new_play_time}_{name}"
    scheduled_tasks[new_task_id] = new_job
    del scheduled_tasks[old_task_id]

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


# 静态文件与前端 SPA 服务
@app.get('/')
async def serve_index():
    index_path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {'code': 200, 'message': '抖音火花助手后端运行中', 'docs': '/docs', 'home': '/Home'}


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


@app.get('/{path:path}')
async def serve_spa(path: str):
    if path.startswith('Api/') or path.startswith('Time/') or path.startswith('Home'):
        return {'error': 'Not found'}
    file_path = os.path.join(STATIC_DIR, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    index_path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {'error': 'Frontend not found'}


if __name__ == "__main__":
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', '9844'))
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False
    )
