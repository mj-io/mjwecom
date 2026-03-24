import requests
import logging
import base64
import json
import uuid
from django.shortcuts import redirect
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from .config import WECOM_CONF, MS_CONF
from urllib.parse import quote

logger = logging.getLogger('wecom')

def wecom_verify(request):
    """
    Step 1: 企业微信二次验证入口 - Correct Implementation
    Docs: https://developer.work.weixin.qq.com/document/path/93438
    """
    session_info = request.GET.get('session_info')
    if not session_info:
        logger.error("'session_info' not found in request from WeCom.")
        return HttpResponse("Invalid request from WeCom: 'session_info' is missing.", status=400)

    # B. 将 session_info 存入 Session，并生成 state 用于 OAuth 流程
    request.session['wecom_session_info'] = session_info
    
    state = str(uuid.uuid4())
    request.session['ms_oauth_state'] = state
    
    logger.info(f"Received WeCom session_info, generated state {state}, redirecting to Entra ID")

    ms_auth_url = (
        f"https://login.microsoftonline.com/{MS_CONF['TENANT_ID']}/oauth2/v2.0/authorize?"
        f"client_id={MS_CONF['CLIENT_ID']}&response_type=code"
        f"&redirect_uri={MS_CONF['REDIRECT_URI']}&response_mode=query"
        f"&scope=openid profile email User.Read"
        f"&state={state}"  # 关键步骤：传递 state
    )
    return redirect(ms_auth_url)


def ms_callback(request):
    """
    Step 2 & 3: 微软回调 -> 账号匹配 -> 通知企微 authed
    """
    ms_code = request.GET.get('code')
    ms_state = request.GET.get('state')
    
    # --- 安全校验：检查 state 和 session ---
    session_state = request.session.get('ms_oauth_state')
    session_info = request.session.get('wecom_session_info')

    logger.info(f'Callback received: ms_code={ms_code}, ms_state={ms_state}')
    logger.info(f'Session state: session_state={session_state}, session_info_exists={bool(session_info)}')

    if not ms_code:
        return HttpResponse("Microsoft Entra ID authentication failed (no code).", status=400)
    if not ms_state or ms_state != session_state:
        logger.warning(f"State mismatch: received '{ms_state}' but expected '{session_state}'. Possible CSRF attack.")
        return HttpResponse("State mismatch. Authentication failed.", status=403)
    if not session_info:
        logger.error("Session expired or invalid: 'wecom_session_info' not found.")
        return HttpResponse("Your session has expired. Please try again.", status=400)
    
    # 清理 session 中的 state
    del request.session['ms_oauth_state']

    # --- Step A: 获取微软 Token ---
    token_url = f"https://login.microsoftonline.com/{MS_CONF['TENANT_ID']}/oauth2/v2.0/token"
    token_payload = {
        "client_id": MS_CONF['CLIENT_ID'],
        "client_secret": MS_CONF['CLIENT_SECRET'],
        "code": ms_code,
        "grant_type": "authorization_code",
        "redirect_uri": MS_CONF['REDIRECT_URI'],
    }
    res = requests.post(token_url, data=token_payload).json()
    access_token = res.get("access_token")

    if not access_token:
        logger.error(f"Failed to get MS token: {res.get('error_description')}")
        return HttpResponse("Failed to get authorization token from Microsoft.", status=500)

    # --- Step B: 账号匹配逻辑 (示例：从Token中获取用户信息) ---
    claims = get_user_info_from_token(access_token)
    if not claims:
        return HttpResponse("Invalid token received from Microsoft.", status=500)

    ms_email = claims.get('upn') or claims.get('email') or claims.get('preferred_username')
    logger.info(f"Successfully authenticated Microsoft user: {ms_email}")
    # 此处可根据业务需求，增加 ms_email 与内部系统的用户绑定校验逻辑

    # --- Step C: 通知企业微信二次验证成功 ---
    wecom_client = WeComProvider(WECOM_CONF["CORP_ID"], WECOM_CONF["SECRET"])
    authed_result = wecom_client.notify_authed(session_info)

    if authed_result.get("errcode") == 0:
        logger.info(f"Successfully notified WeCom 'authed' for session: {session_info[:20]}...")
        # --- Step D: 显示成功页面并自动关闭 ---
        html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=0">
    <title>身份验证成功</title>
    <script type="text/javascript" src="https://res.wx.qq.com/open/js/jweixin-1.2.0.js"></script>
    <style>
        body { font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: #fff; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .container { text-align: center; padding: 20px; }
        .icon { width: 64px; height: 64px; margin-bottom: 20px; }
        .status { color: #06AD56; font-size: 20px; font-weight: 500; margin-bottom: 8px; }
        .desc { color: #888; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <svg class="icon" viewBox="0 0 64 64"><circle cx="32" cy="32" r="32" fill="#06AD56"/><path d="M18 32l10 10 20-20" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <div class="status">验证成功</div>
        <div class="desc">窗口即将自动关闭...</div>
    </div>
    <script type="text/javascript">
        function closeWindow() {
            if (typeof WeixinJSBridge !== "undefined") {
                WeixinJSBridge.call('closeWindow');
            } else if (window.wx && window.wx.closeWindow) {
                wx.closeWindow();
            } else {
                window.close();
            }
        }
        // 延时1.5秒，确保企微客户端能接收到状态更新，避免立即关闭导致流程中断
        setTimeout(closeWindow, 1500);
    </script>
</body>
</html>
"""
        return HttpResponse(html)
    else:
        error_msg = authed_result.get('errmsg', 'Unknown error')
        logger.error(f"Failed to notify WeCom 'authed'. Response: {authed_result}")
        return HttpResponse(f"Failed to notify WeCom, error: {error_msg}")

def get_user_info_from_token(token):
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        
        payload = parts[1]
        padded_payload = payload + '=' * (4 - len(payload) % 4)
        decoded_payload = base64.b64decode(padded_payload).decode('utf-8')
        return json.loads(decoded_payload)
    except Exception as e:
        logger.error(f"Error decoding JWT: {e}")
        return None

# The 'reset_wecom_verify' and 'go_app' functions are unchanged.
# They are kept here to ensure the file replacement is complete.
from django.views.decorators.csrf import csrf_exempt
from .utils import WeComProvider

@csrf_exempt
def reset_wecom_verify(request):
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
    except (json.JSONDecodeError, AttributeError):
        user_id = request.POST.get('user_id')
    
    if not user_id:
        return JsonResponse({'message': 'userid不能为空'}, status=400, json_dumps_params={'ensure_ascii': False})
    
    wecom_client = WeComProvider(WECOM_CONF["CORP_ID"], WECOM_CONF["SECRET"])
    res = wecom_client.refresh_user_status(user_id)
    return JsonResponse(res, json_dumps_params={'ensure_ascii': False})

def go_app(request):
    app = request.GET.get('app')
    if app == 'veeva':
        return HttpResponseRedirect("https://wchat-auth-login.crmdev.veevasfa.com/#/welcome")
