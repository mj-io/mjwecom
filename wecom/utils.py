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
            # 根据官方文档，自建应用网页授权使用 /auth/getuserinfo
            resp = requests.get(f"{self.base_url}/auth/getuserinfo", params=params).json()
            logger.info(f'{resp}')
            if resp.get('errcode') == 0:
                return resp.get('UserId') or resp.get('userid')
            else:
                logger.warning(f"Code换取UserID失败: {resp}")
                return None
        except Exception as e:
            logger.error(f"请求UserInfo接口异常: {e}")
            return None

    def get_tfa_info(self, code):
        """获取二次验证的 tfa_code 和 userid"""
        token = self.get_access_token()
        if not token:
            return None
        url = f"{self.base_url}/auth/get_tfa_info?access_token={token}"
        try:
            resp = requests.post(url, json={'code': code}).json()
            logger.info(f'get_tfa_info resp: {resp}')
            if resp.get('errcode') == 0:
                return {
                    'userid': resp.get('userid'),
                    'tfa_code': resp.get('tfa_code')
                }
            else:
                logger.warning(f"get_tfa_info 失败: {resp}")
                return None
        except Exception as e:
            logger.error(f"请求get_tfa_info接口异常: {e}")
            return None

    def tfa_succ(self, userid, tfa_code):
        """调用通过二次验证接口"""
        token = self.get_access_token()
        if not token:
            return {'errcode': -1, 'errmsg': '获取token失败'}
        url = f"{self.base_url}/user/tfa_succ?access_token={token}"
        payload = {
            'userid': userid,
            'tfa_code': tfa_code
        }
        try:
            resp = requests.post(url, json=payload).json()
            logger.info(f'tfa_succ resp: {resp}')
            return resp
        except Exception as e:
            logger.error(f"请求tfa_succ接口异常: {e}")
            return {'errcode': -1, 'errmsg': str(e)}

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