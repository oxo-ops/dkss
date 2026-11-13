"""One explicit Responses transmission. Never invoked on import; no credentials lookup.

Use only behind ScopedJobBridge's exact-body reservation, after independent data
and spending approval. No count call, proxy, redirects, retries, or CLI. The
credential exists only in this owner and is dropped after the attempted call.
"""
import http.client
import json
import ssl
from .final_gate import RESPONSES_URL


class ResponsesHTTPS:
    def __init__(self, api_key, *, connection_factory=http.client.HTTPSConnection):
        if (not isinstance(api_key, str) or not api_key.strip()
                or any(c in api_key for c in ('\r','\n')) or not callable(connection_factory)):
            raise ValueError('PILOT_CREDENTIAL_REQUIRED')
        self._key = api_key
        self._factory = connection_factory
        self._started = False

    def __call__(self, url, raw):
        if url != RESPONSES_URL or type(raw) is not bytes:
            raise ValueError('PILOT_ENDPOINT_OR_BODY_REJECTED')
        if self._started:
            raise ValueError('PILOT_NO_TRANSPORT_RETRY')
        self._started = True
        key, self._key = self._key, None
        connection = None
        try:
            connection = self._factory('api.openai.com', timeout=120,
                context=ssl.create_default_context())
            connection.request('POST', '/v1/responses', body=raw, headers={
                'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError('PILOT_HTTP_REJECTED')
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise RuntimeError('PILOT_RESPONSE_TOO_LARGE')
            result = json.loads(data)
            if not isinstance(result, dict):
                raise RuntimeError('PILOT_RESPONSE_SHAPE')
            return result
        except Exception:
            raise RuntimeError('PILOT_HTTP_UNCERTAIN') from None
        finally:
            key = None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
