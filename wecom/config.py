import os
from dotenv import load_dotenv
# 企业微信配置
load_dotenv()

WECOM_CONF = {
    "CORP_ID": os.getenv("WECOM_CORP_ID"),
    "SECRET": os.getenv("WECOM_SECRET"),
    "AUTH_SUCC_URL": "https://qyapi.weixin.qq.com/cgi-bin/user/authsucc",
    "CLOSE_HTML": """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>验证成功</title>
            <script src="https://res.wx.qq.com/open/js/jweixin-1.2.0.js"></script>
        </head>
        <body>
            <div style="text-align: center; margin-top: 100px;">
                <h2 style="color: #07C160;">验证成功</h2>
                <p>正在返回企业微信...</p>
            </div>
            <script>
                // 优先使用企业微信特定的关闭接口
                document.addEventListener('DOMContentLoaded', function() {
                    // 如果在企业微信环境下
                    if (typeof WeixinJSBridge !== "undefined") {
                        WeixinJSBridge.call('closeWindow');
                    } else {
                        // 兜底方案
                        window.close();
                    }
                });
            </script>
        </body>
        </html>
        """
}

# 微软 Entra ID 配置
MS_CONF = {
    "TENANT_ID": os.getenv("MS_TENANT_ID"),
    "CLIENT_ID": os.getenv("MS_CLIENT_ID"),
    "CLIENT_SECRET": os.getenv("MS_CLIENT_SECRET"),
    "REDIRECT_URI": "https://mjio.cn/wecom/callback/",
    "TOKEN_URL": "https://login.microsoftonline.com/{}/oauth2/v2.0/token",
    "DOWNSTREAM_SCOPE": os.getenv("MS_DOWNSTREAM_SCOPE"),
    "FINAL_APP_URL": "https://htltio.cn/login"
}
