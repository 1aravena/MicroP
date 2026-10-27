class BackendError(Exception):
    status_code = 409


class ValidationError(BackendError):
    status_code = 422


class NotFound(BackendError):
    status_code = 404


class CommandTimeout(BackendError):
    status_code = 504


class DeviceUnavailable(BackendError):
    status_code = 503


class StorageError(BackendError):
    status_code = 503

