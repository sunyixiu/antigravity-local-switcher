"""Google-only quota queries for the local account switcher. No third-party packages."""
import base64
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from oauth_config import ConfigurationError, local_client_config

TOKEN_URL = "https://oauth2.googleapis.com/token"
CONTEXT_URL = "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
MODEL_URLS = (
    "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
    "https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
    "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:fetchAvailableModels",
)
GROUP_URLS = tuple(url.replace("fetchAvailableModels", "retrieveUserQuotaSummary") for url in (MODEL_URLS[2], MODEL_URLS[1], MODEL_URLS[0]))
USER_INFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
ALLOWED = {TOKEN_URL, CONTEXT_URL, USER_INFO_URL, *MODEL_URLS, *GROUP_URLS}
SINGAPORE = timezone(timedelta(hours=8))
MAX_RESPONSE = 2_000_000


class QuotaError(Exception):
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def retry_after_seconds(value, now=None):
    if not isinstance(value, str):
        return None
    try:
        if value.strip().isdigit():
            return min(86400, int(value.strip()))
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return min(86400, max(0, math.ceil(date.timestamp() - (time.time() if now is None else now))))
    except (ValueError, TypeError, OverflowError):
        return None


class QueryStopped(QuotaError):
    """Local account is no longer eligible; never retry or renew its grant."""


class OfficialRefreshRequired(QuotaError):
    """Wait for the official client to renew the local access token."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authorization-bearing requests must not be redirected to another site.
        return None


def post(url, payload, access=None, form=False, method="POST"):
    if url not in ALLOWED:
        raise QuotaError("拒绝向非指定 Google 接口发送凭据。")
    if method not in ("GET", "POST") or (method == "GET" and url != USER_INFO_URL):
        raise QuotaError("不支持的 Google 查询方法。")
    if method == "GET":
        body = None
        content_type = "application/json"
    elif form:
        body = urllib.parse.urlencode(payload).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    else:
        body = json.dumps(payload).encode("utf-8")
        content_type = "application/json"
    headers = {"Content-Type": content_type, "User-Agent": "antigravity/2.19.1 Windows/amd64"}
    if access:
        headers["Authorization"] = "Bearer " + access
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise QuotaError("Google 返回的数据过大。")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise QuotaError("Google 接口返回了不支持的数据格式。")
        return result
    except urllib.error.HTTPError as error:
        code = error.code
        retry_after = retry_after_seconds(error.headers.get("Retry-After")) if error.headers else None
        error.close()  # Never retain/display provider bodies or request objects.
        message = {400: "授权或请求不兼容，请在官方客户端重新登录并更新快照。", 401: "登录令牌失效，请更新账号快照。", 403: "Google 拒绝额度查询（权限或账号验证问题）。", 429: "查询过于频繁，稍后再试。"}.get(code, f"Google 接口暂不可用（HTTP {code}）。")
        raise QuotaError(message, code, retry_after) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise QuotaError("无法连接 Google；请检查网络或系统代理。") from None
    except (ValueError, UnicodeError):
        raise QuotaError("Google 返回的数据格式无法识别。") from None


def decode(record):
    raw = base64.b64decode(record["blob"], validate=True).decode("utf-8")
    wrapped = raw.startswith("go-keyring-base64:")
    if wrapped:
        raw = base64.b64decode(raw.split(":", 1)[1], validate=True).decode("utf-8")
    value = json.loads(raw)
    return value, value.get("token", value), wrapped


def expiration(token):
    numeric = token.get("expiry_timestamp")
    if isinstance(numeric, (float, int)) and not isinstance(numeric, bool):
        return numeric / 1000 if numeric > 10_000_000_000 else numeric
    value = token.get("expiry")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.timestamp()
        except ValueError:
            pass
    return None


def renew(record, request=post):
    value, token, wrapped = decode(record)
    try:
        client_id, client_secret = local_client_config()
    except ConfigurationError as error:
        raise QuotaError(str(error)) from None
    if token.get("client_id") not in (None, client_id):
        raise QuotaError("该账号使用另一种 OAuth 客户端，当前版本不自动刷新；请更新快照。")
    identity = token.get("id_token")
    if isinstance(identity, str) and identity.count(".") == 2:
        try:
            part = identity.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            audience = claims.get("aud")
            # This unverified claim is only a conservative mismatch hint, never an identity proof.
            if isinstance(audience, str) and audience.endswith(".apps.googleusercontent.com") and audience != client_id:
                raise QuotaError("快照属于另一种 Google 登录客户端，请在官方客户端更新快照。")
        except (ValueError, UnicodeError, AttributeError):
            pass
    refresh = token.get("refresh_token")
    if not isinstance(refresh, str) or not refresh.strip():
        raise QuotaError("快照缺少刷新令牌，请重新登录并保存。")
    result = request(TOKEN_URL, {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh, "grant_type": "refresh_token"}, form=True)
    access = result.get("access_token")
    seconds = result.get("expires_in")
    if not isinstance(access, str) or not access or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds < 604800:
        raise QuotaError("Google 没有返回可用的新令牌。")
    token["access_token"] = access
    token["expiry"] = datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat().replace("+00:00", "Z")
    if "expiry_timestamp" in token:
        token["expiry_timestamp"] = int(time.time() + seconds)
    # id_token is not used by the official desktop token format; persisting it
    # can exceed Windows credential capacity after an otherwise valid refresh.
    token.pop("id_token", None)
    for key in ("refresh_token", "token_type"):
        if isinstance(result.get(key), str) and result[key]:
            token[key] = result[key]
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if wrapped:
        raw = ("go-keyring-base64:" + base64.b64encode(raw).decode("ascii")).encode("utf-8")
    return dict(record, blob=base64.b64encode(raw).decode("ascii"))


def parse_models(response):
    source = response.get("models")
    if not isinstance(source, dict):
        raise QuotaError("额度接口未返回模型列表。")
    rows = []
    for model_id, value in source.items():
        if not isinstance(model_id, str) or not isinstance(value, dict):
            continue
        if not any(name in model_id.casefold() for name in ("gemini", "claude", "gpt")):
            continue
        quota = value.get("quotaInfo")
        if not isinstance(quota, dict):
            continue
        fraction = quota.get("remainingFraction")
        percentage = None
        if isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and math.isfinite(fraction) and 0 <= fraction <= 1:
            percentage = round(fraction * 100, 1)
        reset = quota.get("resetTime")
        display = value.get("displayName")
        rows.append({"id": model_id[:200], "name": display[:200] if isinstance(display, str) else model_id[:200], "percentage": percentage, "reset": reset[:100] if isinstance(reset, str) else ""})
    if not rows:
        raise QuotaError("Google 未提供可识别的模型额度数据。")
    return sorted(rows, key=lambda row: row["id"])


def families(text):
    result = set()
    text = text.casefold()
    if "gemini" in text:
        result.add("gemini")
    if any(value in text for value in ("claude", "gpt", "anthropic", "third-party", "third party")) or re.search(r"(?:^|[^a-z0-9])3p(?:$|[^a-z0-9])", text):
        result.add("thirdparty")
    return result


def bucket_window(bucket):
    text = " ".join(str(bucket.get(key, "")) for key in ("window", "bucketId", "displayName", "description")).casefold()
    normalized = re.sub(r"[^a-z0-9]", "", str(bucket.get("window", "")).casefold())
    if "week" in text or normalized in ("7d", "p7d", "168h", "604800s"):
        return "weekly"
    if normalized in ("5h", "pt5h", "18000s", "fivehour", "fivehours", "fivehourlimit", "fivehourslimit") or re.search(r"(?:^|[^a-z0-9])5[ _-]?(?:h|hours?)(?:$|[^a-z0-9])|five[ _-]+hours?", text):
        return "5h"
    return None


def parse_groups(response):
    source = response.get("groups")
    if not isinstance(source, list):
        raise QuotaError("Google 未返回每周/五小时额度分组。")
    rows = []
    for group in source:
        if not isinstance(group, dict) or not isinstance(group.get("buckets"), list):
            continue
        group_name = str(group.get("displayName", ""))[:200]
        group_families = families(group_name + " " + str(group.get("description", "")))
        for bucket in group["buckets"]:
            if not isinstance(bucket, dict):
                continue
            bucket_families = families(" ".join(str(bucket.get(key, "")) for key in ("bucketId", "displayName", "description")))
            matched = bucket_families or group_families
            family = next(iter(matched)) if len(matched) == 1 else None
            fraction = bucket.get("remainingFraction")
            percentage = None
            if isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and math.isfinite(fraction) and 0 <= fraction <= 1:
                percentage = math.floor(fraction * 100 + 0.5)
            rows.append({"family": family, "window": bucket_window(bucket), "percentage": percentage,
                         "group": group_name, "id": str(bucket.get("bucketId", ""))[:200],
                         "name": str(bucket.get("displayName") or bucket.get("window") or bucket.get("bucketId") or "未识别窗口")[:200],
                         "reset": bucket.get("resetTime", "")[:100] if isinstance(bucket.get("resetTime", ""), str) else ""})
    if not rows:
        raise QuotaError("Google 的每周/五小时额度分组为空。")
    return rows


def window_percentage(cache, family, window):
    values = [row["percentage"] for row in cache.get("groups", []) if row.get("family") == family and row.get("window") == window and isinstance(row.get("percentage"), (int, float))]
    return min(values) if values else None


def window_summary(cache, family, window):
    percentage = window_percentage(cache, family, window)
    return f"{percentage:g}%" if percentage is not None else "未知"


def query(record, request=post, on_renew=lambda record: None, allow_renew=False):
    original = record
    _, token, _ = decode(record)
    due = expiration(token)
    refreshed = False
    if not token.get("access_token") or (due is not None and due <= time.time() + 30):
        if not allow_renew:
            raise OfficialRefreshRequired("等待 Antigravity 更新登录授权；请打开官方客户端完成登录后再查询。", 401)
        record = renew(record, request)
        on_renew(record)  # Keep successfully refreshed credentials even if the quota endpoint fails.
        refreshed = True

    def fetch(current):
        _, current_token, _ = decode(current)
        access = current_token.get("access_token")
        if not isinstance(access, str) or not access:
            raise QuotaError("账号没有可用的访问令牌。")
        project = current_token.get("project_id")
        tier = ""
        try:
            context = request(CONTEXT_URL, {"metadata": {"ideType": "ANTIGRAVITY"}}, access=access)
            candidate = context.get("cloudaicompanionProject")
            if isinstance(candidate, str) and candidate:
                project = candidate
            elif isinstance(candidate, dict) and isinstance(candidate.get("id"), str):
                project = candidate["id"]
            subscription = context.get("paidTier") or context.get("currentTier")
            if isinstance(subscription, dict) and isinstance(subscription.get("id"), str):
                tier = subscription["id"][:100]
        except QuotaError as error:
            if isinstance(error, QueryStopped) or error.status in (401, 429):
                raise
        payload = {"project": project} if isinstance(project, str) and project else {}

        def endpoint_data(endpoints, parser):
            for index, endpoint in enumerate(endpoints):
                try:
                    try:
                        response = request(endpoint, payload, access=access)
                    except QuotaError as error:
                        if error.status == 403 and payload:
                            response = request(endpoint, {}, access=access)
                        else:
                            raise
                    return parser(response)
                except QuotaError as error:
                    if index + 1 < len(endpoints) and error.status in (404, 500, 502, 503, 504):
                        continue
                    raise

        groups, models = [], []
        group_error = model_error = None
        try:
            groups = endpoint_data(GROUP_URLS, parse_groups)
        except QuotaError as error:
            if isinstance(error, QueryStopped) or error.status == 401:
                raise
            group_error = str(error)
        try:
            models = endpoint_data(MODEL_URLS, parse_models)
        except QuotaError as error:
            if isinstance(error, QueryStopped) or error.status == 401:
                raise
            model_error = error
        if not groups and not models:
            raise model_error or QuotaError(group_error or "未获取到额度数据。")
        status = "已更新"
        if not groups:
            status = "周/5小时未获取"
        elif not models:
            status = "已更新；模型详情未获取"
        return {"models": models, "groups": groups, "tier": tier, "updated": time.time(),
                "status": status, "group_error": group_error, "model_error": str(model_error) if model_error else None}

    try:
        result = fetch(record)
    except QuotaError as error:
        if isinstance(error, QueryStopped) or error.status != 401 or refreshed:
            raise
        if not allow_renew:
            raise OfficialRefreshRequired("Google 未接受当前访问令牌，等待 Antigravity 更新授权；工具不会自行续期。", 401) from None
        record = renew(original, request)
        on_renew(record)
        result = fetch(record)
    return result


def summary(cache, family):
    rows = [row for row in cache.get("models", []) if family in row.get("id", "").casefold()]
    values = [row["percentage"] for row in rows if isinstance(row.get("percentage"), (float, int))]
    if not values:
        return "未知"
    value = min(values)  # Lowest model quota in this family; never sum shared budgets.
    return f"{value:g}%"


def reset_display(value):
    if not value:
        return "未知"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return "未知"
        return parsed.astimezone(SINGAPORE).strftime("%m-%d %H:%M")
    except ValueError:
        return "未知"
