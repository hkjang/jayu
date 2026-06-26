from __future__ import annotations

from typing import Literal

PermissionMode = Literal["read_only", "review_only", "approve_enabled", "admin"]


class DashboardPermissionModeManager:
    def __init__(self, default_mode: PermissionMode = "read_only"):
        self.current_mode: PermissionMode = default_mode

    def set_mode(self, mode: PermissionMode) -> None:
        self.current_mode = mode

    def get_mode(self) -> PermissionMode:
        return self.current_mode

    def is_action_allowed(self, action: str) -> bool:
        """Evaluates whether the requested action is allowed under the current permission mode.
        Action types:
          - 'view': Read-only dashboard access.
          - 'write_memo', 'update_routine': Adding notes or changing routine check status.
          - 'record_approval': Approving/suspending/ignoring system trade signals.
          - 'modify_settings', 'trigger_backup', 'trigger_restore': Writing config or modifying core systems.
        """
        mode = self.current_mode

        if mode == "admin":
            return True
            
        if mode == "approve_enabled":
            return action in {"view", "write_memo", "update_routine", "record_approval"}
            
        if mode == "review_only":
            return action in {"view", "write_memo", "update_routine"}
            
        if mode == "read_only":
            return action == "view"

        return False
