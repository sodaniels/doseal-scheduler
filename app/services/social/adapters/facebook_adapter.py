import requests, os

class FacebookAdapter:
    GRAPH = os.getenv("FACEBOOK_GRAPH_API_URL", "https://graph.facebook.com/v20.0")

    @classmethod
    def list_pages(cls, user_access_token: str):
        url = f"{cls.GRAPH}/me/accounts"
        params = {
            "fields": "id,name,access_token,category,tasks",
            "access_token": user_access_token
        }
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if r.status_code != 200:
            raise Exception(f"Meta error: {data}")
        return data.get("data", [])