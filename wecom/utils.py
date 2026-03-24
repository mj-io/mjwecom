import requests
import logging

logger = logging.getLogger('wecom')

class WeComProvider:
    def __init__(self, corp_id, secret):
        self.corp_id = corp_id
        self.secret = secret
        self.base_url = "https://qyapi.weixin.qq.com/cgi-bin"

    def get_access_token(self):
        """获取企业微信应用 token"""
        params = {
            'corpid': self.corp_id,
            'corpsecret': self.secret
        }
        try:
            resp = requests.get(f"{self.base_url}/gettoken", params=params).json()
            if resp.get('errcode') == 0:
                return resp.get('access_token')
            else:
                logger.error(f"获取Token失败: {resp}")
                return None
        except Exception as e:
            logger.error(f"请求Token接口异常: {e}")
            return None

    def get_user_info(self, code):
        """根据 code 获取 UserID"""
        token = self.get_access_token()
        if not token:
            return None

        params = {'access_token': token, 'code': code}
        try:
            resp = requests.get(f"{self.base_url}/user/getuserinfo", params=params).json()
            # 注意：二次验证场景下，这里返回的是 UserID
            logger.info(f'{resp}')
            if resp.get('errcode') == 0:
                return resp.get('UserId')
            else:
                logger.warning(f"Code换取UserID失败: {resp}")
                return None
        except Exception as e:
            logger.error(f"请求UserInfo接口异常: {e}")
            return None

    def notify_authed(self, session_info):
        """
        通知企业微信二次验证成功
        Docs: https://developer.work.weixin.qq.com/document/path/93438
        """
        token = self.get_access_token()
        if not token:
            return {'errcode': -1, 'errmsg': 'Failed to get access_token'}

        params = {'access_token': token, 'session_info': session_info}
        try:
            resp = requests.get(f"{self.base_url}/user/authed", params=params).json()
            return resp
        except Exception as e:
            logger.error(f"请求 authed 接口异常: {e}")
            return {'errcode': -2, 'errmsg': str(e)}

    # 尝试通过更新成员自定义字段来刷新状态
    def refresh_user_status(self, user_id):
        access_token=self.get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/user/update?access_token={access_token}"
        payload = {
            "userid": user_id,
            "external_profile": {
                "external_attr": [
                    {"type": 0, "name": "LastVerifyReset", "text": {"value": "2026-01-22"}}
                ]
            }
        }
        return requests.post(url, json=payload).json()
