import contextlib
import copy
import datetime
import json
import logging
from json import JSONDecodeError

import requests

from . import models

logger = logging.getLogger("default")


@contextlib.contextmanager
def log_request(attrs_to_mask=("Authorization", "access_token", "token", "refresh_token")):
    original_request = requests.sessions.Session.request
    log_service = RequestLogService()

    def logged_request(self, method, url, **kwargs):
        nonlocal attrs_to_mask

        default_log_request_data = RequestLogService.default_log_request_data(
            url=url,
            method=method,
            attrs_to_mask=attrs_to_mask,
            request_payload=kwargs.get("data") or kwargs.get("json"),
            request_headers=kwargs.get("headers"),
            request_query_params=kwargs.get("params"),
        )
        try:
            response = original_request(self, method, url, **kwargs)
        except Exception as e:
            end_time = datetime.datetime.now()
            logger.error(
                f"ВНЕШНИЙ ЗАПРОС {url}",
                extra={
                    **default_log_request_data,
                    "exception": str(e),
                    "duration_ms": end_time - default_log_request_data.get("request_timestamp"),
                },
            )
            log_service.create_log(
                **default_log_request_data,
                message=str(e),
                response_timestamp=end_time,
                attrs_to_mask=attrs_to_mask,
            )
            raise
        try:
            response_data = response.json()
        except JSONDecodeError:
            response_data = {}
        end_time = datetime.datetime.now()
        logger.info(
            f"ВНЕШНИЙ ЗАПРОС {url}",
            extra={
                **default_log_request_data,
                "response_data": json.dumps(RequestLogService.mask_attrs(attrs_to_mask, response_data),
                                            ensure_ascii=False),
                "status_code": response.status_code,
                "duration_ms": end_time - default_log_request_data.get("request_timestamp"),
                "response_headers": json.dumps(
                    RequestLogService.mask_attrs(attrs_to_mask, dict(response.headers)),
                    ensure_ascii=False
                ),

                "request_headers": RequestLogService.mask_attrs(attrs_to_mask, kwargs.get("headers", {})),
            },
        )
        log_service.create_log(
            **default_log_request_data,
            response_data=response_data,
            response_status_code=response.status_code,
            response_headers=dict(response.headers),
            response_timestamp=end_time,
            attrs_to_mask=attrs_to_mask,
        )
        return response

    requests.sessions.Session.request = logged_request
    try:
        yield
    finally:
        requests.sessions.Session.request = original_request


class RequestLogService:
    def create_log(self, attrs_to_mask: tuple, **kwargs) -> models.RequestLog:
        data = self._get_request_log_data(attrs_to_mask=attrs_to_mask, **kwargs)
        return models.RequestLog.objects.create(**data)

    def _get_request_log_data(self, attrs_to_mask: tuple, **kwargs) -> dict:
        return {
            "request_payload": self.mask_attrs(attrs_to_mask, kwargs.get("request_payload", {})),
            "request_url": kwargs["request_url"],
            "request_method": kwargs["request_method"],
            "request_headers": self.mask_attrs(attrs_to_mask, kwargs.get("request_headers", {})),
            "response_data": self.mask_attrs(attrs_to_mask, kwargs.get("response_data", {})),
            "request_query_params": self.mask_attrs(attrs_to_mask, kwargs.get("request_query_params", {})),
            "response_status_code": kwargs.get("response_status_code", None),
            "response_headers": self.mask_attrs(attrs_to_mask, kwargs.get("response_headers", {})),
            "request_timestamp": kwargs["request_timestamp"],
            "response_timestamp": kwargs["response_timestamp"],
            "message": kwargs.get("message", ""),
        }

    @staticmethod
    def mask_attrs(attrs_to_mask: tuple, request_attrs: dict) -> dict:
        request_attrs = copy.deepcopy(request_attrs)
        if request_attrs and isinstance(request_attrs, dict):
            for attr_to_mask in attrs_to_mask:
                if (request_attr_to_mask := request_attrs.get(attr_to_mask, None)) is not None:
                    length = len(request_attr_to_mask)
                    cut = int(length * 0.2)

                    if length < 5 or cut * 2 >= length:
                        request_attrs[attr_to_mask] = "*" * length
                    else:
                        left = request_attr_to_mask[:cut]
                        right = request_attr_to_mask[-cut:]
                        middle_len = length - cut * 2
                        request_attrs[attr_to_mask] = left + "*" * middle_len + right
        return request_attrs

    @staticmethod
    def default_log_request_data(
            url: str,
            method: str,
            attrs_to_mask: tuple = (),
            request_payload: dict = None,
            request_headers: dict = None,
            request_query_params: dict = None,
    ) -> dict:
        return {
            "request_payload": json.dumps(
                RequestLogService.mask_attrs(attrs_to_mask, request_payload), ensure_ascii=False
            ) if request_payload else {},
            "request_url": url,
            "request_method": method,
            "request_headers": json.dumps(
                RequestLogService.mask_attrs(attrs_to_mask, request_headers), ensure_ascii=False
            ) if request_headers else {},
            "request_timestamp": datetime.datetime.now(),
            "request_query_params": json.dumps(
                RequestLogService.mask_attrs(attrs_to_mask, request_query_params), ensure_ascii=False
            ) if request_query_params else {},
        }
