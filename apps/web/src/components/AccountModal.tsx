import React, { useState } from "react";
import { KeyRound, Loader2, X } from "lucide-react";
import { api } from "../api";

interface AccountModalProps {
  open: boolean;
  username: string;
  onClose: () => void;
  onSuccess: (msg: string) => void;
}

export const AccountModal: React.FC<AccountModalProps> = ({
  open,
  username,
  onClose,
  onSuccess,
}) => {
  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!currentPwd) {
      setError("请输入当前密码");
      return;
    }
    if (newPwd.length < 8) {
      setError("新密码至少需要 8 位字符");
      return;
    }
    if (newPwd !== confirmPwd) {
      setError("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await api.changePassword(currentPwd, newPwd);
      setCurrentPwd("");
      setNewPwd("");
      setConfirmPwd("");
      onClose();
      onSuccess("密码已更新，其他设备会话已全部吊销");
    } catch (err) {
      setError((err as Error).message || "修改失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-studio-border bg-studio-panel p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <KeyRound className="h-4 w-4 text-indigo-400" />
            <h2 className="text-sm font-semibold text-white">账号安全（{username}）</h2>
          </div>
          <button className="studio-btn-ghost" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3.5 text-xs">
          <div>
            <label className="mb-1 block text-slate-300">当前密码</label>
            <input
              type="password"
              autoComplete="current-password"
              className="studio-input"
              value={currentPwd}
              onChange={(e) => setCurrentPwd(e.target.value)}
              disabled={saving}
            />
          </div>
          <div>
            <label className="mb-1 block text-slate-300">新密码（至少 8 位）</label>
            <input
              type="password"
              autoComplete="new-password"
              className="studio-input"
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
              disabled={saving}
            />
          </div>
          <div>
            <label className="mb-1 block text-slate-300">确认新密码</label>
            <input
              type="password"
              autoComplete="new-password"
              className="studio-input"
              value={confirmPwd}
              onChange={(e) => setConfirmPwd(e.target.value)}
              disabled={saving}
            />
          </div>

          {error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-950/60 px-3 py-2 text-rose-200">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="studio-btn-secondary" onClick={onClose} disabled={saving}>
              取消
            </button>
            <button type="submit" className="studio-btn-primary" disabled={saving}>
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              更新密码
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
