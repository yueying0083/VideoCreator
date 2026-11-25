import React, { useState } from "react";
import { Clapperboard, Eye, EyeOff, Loader2, Lock, ShieldCheck, UserCheck } from "lucide-react";
import { api } from "../api";
import type { AuthStatus } from "../types";

interface AuthScreenProps {
  status: AuthStatus;
  onAuthenticated: (next: AuthStatus) => void;
}

export const AuthScreen: React.FC<AuthScreenProps> = ({ status, onAuthenticated }) => {
  const isSetup = !status.initialized;
  const [username, setUsername] = useState(isSetup ? "admin" : "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPwd, setShowPwd] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmedUser = username.trim();
    if (!trimmedUser) {
      setError("请输入用户名");
      return;
    }
    if (isSetup) {
      if (password.length < 8) {
        setError("管理员密码至少需要 8 位字符");
        return;
      }
      if (password !== confirmPassword) {
        setError("两次输入的密码不一致");
        return;
      }
    } else if (!password) {
      setError("请输入密码");
      return;
    }

    setSubmitting(true);
    try {
      const next = isSetup
        ? await api.setupAdmin(trimmedUser, password)
        : await api.login(trimmedUser, password, remember);
      onAuthenticated(next);
    } catch (err) {
      setError((err as Error).message || "认证失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-studio-bg px-4 py-10 text-slate-100">
      <div className="w-full max-w-md rounded-2xl border border-studio-border bg-studio-panel p-7 shadow-2xl">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-600/20 text-indigo-400 ring-1 ring-indigo-500/40">
            <Clapperboard className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-white">Video Creator Studio</h1>
            <p className="text-xs text-slate-400">
              {isSetup ? "首次启用 · 创建唯一管理员账号" : "私密工作台 · 管理员登录"}
            </p>
          </div>
        </div>

        {isSetup && (
          <div className="mb-5 flex items-start gap-2.5 rounded-xl border border-indigo-500/30 bg-indigo-500/10 p-3 text-xs leading-relaxed text-indigo-200">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-indigo-400" />
            <span>
              该服务部署在公网。设置管理员账号并完成后，公开注册入口将永久关闭，后续仅支持此账号登录与改密。
            </span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-slate-300">用户名</label>
            <div className="relative">
              <UserCheck className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
              <input
                autoFocus
                autoComplete="username"
                className="studio-input pl-9"
                placeholder="3~32 位字母/数字/._-"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={submitting}
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-medium text-slate-300">
              {isSetup ? "管理员密码（至少 8 位）" : "密码"}
            </label>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
              <input
                type={showPwd ? "text" : "password"}
                autoComplete={isSetup ? "new-password" : "current-password"}
                className="studio-input pl-9 pr-10"
                placeholder={isSetup ? "请输入高强度密码（≥ 8 位）" : "请输入密码"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
              />
              <button
                type="button"
                className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-200"
                onClick={() => setShowPwd((v) => !v)}
                tabIndex={-1}
                title={showPwd ? "隐藏密码" : "显示密码"}
              >
                {showPwd ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {isSetup ? (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-300">确认密码</label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                <input
                  type={showPwd ? "text" : "password"}
                  autoComplete="new-password"
                  className="studio-input pl-9"
                  placeholder="再次输入密码"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={submitting}
                />
              </div>
            </div>
          ) : (
            <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-slate-600 bg-studio-bg text-indigo-500"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                disabled={submitting}
              />
              <span>记住登录状态（14 天内免重复登录）</span>
            </label>
          )}

          {error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-950/60 px-3 py-2 text-xs text-rose-200">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="studio-btn-primary w-full justify-center py-2.5 text-sm font-medium"
          >
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            {isSetup ? "创建管理员并进入工作台" : "登录工作台"}
          </button>
        </form>
      </div>
    </div>
  );
};
