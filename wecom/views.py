import requests
import logging
import base64
import json
from django.shortcuts import redirect
from django.http import HttpResponse, JsonResponse,HttpResponseRedirect
from .config import WECOM_CONF, MS_CONF
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect
from urllib.parse import quote
from .utils import WeComProvider


logger = logging.getLogger('wecom')

def wecom_verify(request):
    """
    Step 1: 企业微信二次验证入口
    URL: https://mjio.cn/wecom/verify/?code=CODE
    """
    code = request.GET.get('code')
    if not code:
        corp_id = WECOM_CONF["CORP_ID"]
        # 必须是你在企微后台配置的可信域名下的地址
        redirect_uri = quote("https://mjio.cn/wecom/verify/")
        auth_url = (
            f"https://open.weixin.qq.com/connect/oauth2/authorize?"
            f"appid={corp_id}&redirect_uri={redirect_uri}&"
            f"response_type=code&scope=snsapi_base&state=STATE#wechat_redirect"
        )
        return redirect(auth_url)


    # A. 换取企业微信 UserID
    
    wecom_client = WeComProvider(WECOM_CONF["CORP_ID"], WECOM_CONF["SECRET"])
    access_token = wecom_client.get_access_token()
    
    tfa_info = wecom_client.get_tfa_info(code)
    
    if tfa_info and tfa_info.get('userid'):
        user_id = tfa_info.get('userid')
        tfa_code = tfa_info.get('tfa_code')
    else:
        user_id = wecom_client.get_user_info(code)
        tfa_code = None

    if not user_id:
        logger.error(f"Failed to get WeCom UserID for code {code}")
        return HttpResponse("WeCom Auth Failed", status=403)

    # B. 存入 Session 并跳转微软
    request.session['temp_wecom_userid'] = user_id
    request.session['temp_wecom_tfacode'] = tfa_code
    request.session['accesstoken'] = access_token
    logger.info(f"WeCom User identified: {user_id}, redirecting to Entra ID")

    ms_auth_url = (
        f"https://login.microsoftonline.com/{MS_CONF['TENANT_ID']}/oauth2/v2.0/authorize?"
        f"client_id={MS_CONF['CLIENT_ID']}&response_type=code"
        f"&redirect_uri={MS_CONF['REDIRECT_URI']}&response_mode=query"
        f"&scope=openid profile email User.Read"
    )
    return redirect(ms_auth_url)


def ms_callback(request):
    """
    Step 2 & 3: 微软回调 -> 账号匹配 -> OBO 换 Token -> 企微 authsucc
    URL: https://mjio.cn/wecom/callback/
    """
    ms_code = request.GET.get('code')
    wecom_userid = request.session.get('temp_wecom_userid')
    tfa_code = request.session.get('temp_wecom_tfacode')
    access_token = request.session.get('accesstoken')
    logger.info(f'mscode={ms_code}, wecom_userid={wecom_userid}')

    if not ms_code or not wecom_userid:
        return HttpResponse("Session expired or MS auth failed", status=400)

    # --- Step A: 获取 Token A (mjio.cn 的 Access Token) ---
    token_url = MS_CONF["TOKEN_URL"].format(MS_CONF["TENANT_ID"])
    logger.info(f'token_url={token_url}')
    token_a_payload = {
        "client_id": MS_CONF["CLIENT_ID"],
        "client_secret": MS_CONF["CLIENT_SECRET"],
        "code": ms_code,
        "grant_type": "authorization_code",
        "redirect_uri": MS_CONF["REDIRECT_URI"],
        "scope": f"api://{MS_CONF['CLIENT_ID']}/.default" # 获取 Token A 的 Scope
    }
    res_a = requests.post(token_url, data=token_a_payload).json()
    access_token_a = res_a.get("access_token")
    logger.info(f'res_a={res_a}')

    # --- Step B: 账号匹配逻辑 (示例：获取微软 Email) ---
    #user_info = requests.get(
    #    "https://graph.microsoft.com/v1.0/me",
    #    headers={"Authorization": f"Bearer {access_token_a}"}
    #).json()
    #logger.info(f'user_info={user_info}')
    #ms_email = user_info.get("mail") or user_info.get("userPrincipalName")
    claims = get_user_info_from_token(access_token_a)
    logger.info(f"claims={claims}")
    ms_email = claims.get('upn') or claims.get('email') or claims.get('preferred_username')
    
    logger.info(f"Matching WeCom[{wecom_userid}] with MS[{ms_email}]")
    # 此处可增加自定义逻辑：例如从数据库查 user_id 是否关联了该 email

    # --- Step C: OBO 流程 (获取 Token B 访问 veevasfa) ---
    #obo_payload = {
    #    "client_id": MS_CONF["CLIENT_ID"],
    #    "client_secret": MS_CONF["CLIENT_SECRET"],
    #    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
    #    "assertion": access_token_a,
    #    "requested_token_use": "on_behalf_of",
    #    "scope": MS_CONF["DOWNSTREAM_SCOPE"]
    #}
    ## 明确指定 Content-Type (虽然 requests 在使用 data= 时通常会自动处理)
    #headers = {
    #    'Content-Type': 'application/x-www-form-urlencoded'
    #}
    #res_b = requests.post(token_url, data=obo_payload, headers=headers).json()
    #access_token_b = res_b.get("access_token")

    #if not access_token_b:
    #    logger.error(f"OBO Exchange Failed: {res_b}")
    #    return HttpResponse("OBO Exchange Failed", status=500)

    ## --- Step D: 通知企业微信二次验证成功 ---
    ## 需要先拿新的或者重用之前的 WeCom Access Token
    if not access_token:
        wecom_token_resp = requests.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": WECOM_CONF["CORP_ID"], "corpsecret": WECOM_CONF["SECRET"]}
        ).json()
        access_token = wecom_token_resp.get("access_token")
     
    logger.info(f"wecom access_token is {access_token}")
    wecom_client = WeComProvider(WECOM_CONF["CORP_ID"], WECOM_CONF["SECRET"])

    if tfa_code:
        auth_succ_resp = wecom_client.tfa_succ(wecom_userid, tfa_code)
    else:
        auth_succ_resp = requests.get(
            WECOM_CONF["AUTH_SUCC_URL"],
            params={"access_token": access_token, "userid": wecom_userid}
        ).json()
        
    logger.info(f"wecom auth success response {auth_succ_resp}")
    if auth_succ_resp.get("errcode") == 0:
        logger.info(f"WeCom authsucc called for {wecom_userid}")
        # --- Step E: 携带 Token B 跳转最终应用 ---
        #return redirect(MS_CONF["FINAL_APP_URL"].format(access_token_b))

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
            <div class="desc">正在为您同步状态，请稍候...</div>
        </div>

        <script type="text/javascript">
            function forceClose() {
                // 方案1：调用企业微信原生关闭窗口接口
                if (typeof WeixinJSBridge !== "undefined") {
                    WeixinJSBridge.call('closeWindow');
                }
                // 方案2：JSSDK 标准接口
                if (window.wx && window.wx.closeWindow) {
                    wx.closeWindow();
                }
                // 方案3：尝试直接关闭
                window.close();
            }

            // 核心逻辑：等待 JSSDK 就绪 + 适当延时
            function initClose() {
                // 设置 1.5 秒延时，确保企微后台状态同步完成，防止重复触发验证
                setTimeout(function() {
                    forceClose();
                }, 1500);
            }

            if (typeof WeixinJSBridge === "undefined") {
                document.addEventListener('WeixinJSBridgeReady', initClose, false);
            } else {
                initClose();
            }

            // 兜底方案：5秒后如果还没关闭，强制再次尝试
            setTimeout(forceClose, 5000);
        </script>
    </body>
    </html>
"""
        return HttpResponse(html)
    else:
        return HttpResponse(f"WeCom Success Notify Failed: {auth_succ_resp.get('errmsg')}")

def get_user_info_from_token(token):
    # JWT 由三部分组成：Header.Payload.Signature
    # 我们只需要解析中间的 Payload
    parts = token.split('.')
    if len(parts) != 3:
        return None
    
    # 补齐 base64 填充符并解码
    payload = parts[1]
    padded_payload = payload + '=' * (4 - len(payload) % 4)
    decoded_payload = base64.b64decode(padded_payload).decode('utf-8')
    return json.loads(decoded_payload)

@csrf_exempt
def reset_wecom_verify(request):
    try:
        # 处理 Postman raw JSON 提交
        data = json.loads(request.body)
        user_id = data.get('user_id')
    except (json.JSONDecodeError, AttributeError):
        # 处理 form-data 提交
        user_id = request.POST.get('user_id')
    logger.info(f"user_id={user_id}")
    if not user_id:
        return JsonResponse({'message': 'userid不能为空'}, status=400, json_dumps_params={'ensure_ascii': False})
    wecom_client = WeComProvider(WECOM_CONF["CORP_ID"], WECOM_CONF["SECRET"])
    res = wecom_client.refresh_user_status(user_id)
    return JsonResponse(res, json_dumps_params={'ensure_ascii': False})

def go_app(request):
    app = request.GET.get('app')
    if app == 'veeva':
        return HttpResponseRedirect("https://wchat-auth-login.crmdev.veevasfa.com/#/welcome")