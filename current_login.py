"""Identify the actual local login without making Google requests or exposing grants."""
import account_discovery
import local_switcher as core


class CurrentLogin:
    def __init__(self):
        self.bindings = {}

    def bind(self, current_stamp, filename, saved_stamp):
        self.bindings[current_stamp] = (filename, saved_stamp)
        self.bindings = dict(list(self.bindings.items())[-32:])

    def rotated(self, filename, before, after):
        old = account_discovery.fingerprint(before)
        new = account_discovery.fingerprint(after)
        for stamp, binding in list(self.bindings.items()):
            if binding == (filename, old):
                self.bindings[stamp] = (filename, new)

    def resolve(self, store, vault, filenames, verified_binding=None):
        try:
            current = store.read()
            if current is None:
                return {'status': 'signed-out', 'message': 'Antigravity 当前未登录。'}
            stamp = account_discovery.fingerprint(current)
            records = {name: account_discovery.fingerprint(vault.load(name)['credential']) for name in filenames}
            exact = [name for name, saved_stamp in records.items() if saved_stamp == stamp]
            if len(exact) > 1:
                return {'status': 'ambiguous', 'message': '当前登录匹配多个快照，请核对重复账号。'}
            if exact:
                name = exact[0]
                self.bind(stamp, name, records[name])
                return {'status': 'matched', 'id': name}
            if verified_binding is not None:
                verified_stamp, name, saved_stamp = verified_binding
                if stamp == verified_stamp and records.get(name) == saved_stamp:
                    self.bind(stamp, name, saved_stamp)
            binding = self.bindings.get(stamp)
            if binding and records.get(binding[0]) == binding[1]:
                return {'status': 'matched', 'id': binding[0]}
            return {'status': 'unmatched', 'message': '当前登录尚未匹配已保存账号，请扫描账号确认。'}
        except (core.LocalError, OSError, ValueError, TypeError, KeyError):
            return {'status': 'error', 'message': '当前登录暂时无法核对，请检查本地凭据或重新扫描。'}
