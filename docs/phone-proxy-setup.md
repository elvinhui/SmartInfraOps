# 📱 手机代理部署指南 — SmartInfraOps Phone Proxy Setup

> 将你的 Android 手机变成 GitHub Actions 的 SOCKS5 代理跳板，让 Playwright 通过手机的住宅/移动 IP 访问 X (Twitter)。

## 架构概览

```
GHA (ubuntu) ──Tailscale WireGuard──→ 你的手机 (gost SOCKS5) ──WiFi/4G/5G──→ X.com
```

- ✅ WiFi 和移动数据都能用
- ✅ 免费（Tailscale 个人版免费，gost 开源）
- ✅ 无需 VPS、无需公网 IP、无需端口映射

---

## 前置条件

| 项目 | 要求 |
|------|------|
| Android 版本 | 7.0+ |
| 存储空间 | ~50MB (Termux + gost + Tailscale) |
| 已有 Tailscale 账号 | ✅ elvinhui@github |

## Step 1: 安装 Termux

> ⚠️ **必须从 F-Droid 安装 Termux**，Google Play 版本已过期且无法正常工作。

1. 手机浏览器打开 https://f-droid.org/packages/com.termux/
2. 下载并安装 Termux
3. 同时安装以下两个插件：
   - [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) — 开机自启
   - [Termux:API](https://f-droid.org/packages/com.termux.api/) — wake lock 支持

4. **首次打开 Termux:Boot**（打开后直接关掉即可，这一步让 Android 注册开机启动权限）

## Step 2: 运行一键安装脚本

在 Termux 中执行：

```bash
# 更新 Termux 包管理器
pkg update -y && pkg install -y git

# 克隆仓库
git clone https://github.com/elvinhui/SmartInfraOps.git
cd SmartInfraOps

# 切换到部署分支
git checkout deploy-router-proxy-tunnel

# 运行安装脚本
bash router/termux-setup.sh
```

脚本会自动：
1. 安装 Tailscale 和 gost
2. 启动 Tailscale（首次需要在浏览器中登录）
3. 生成 SOCKS5 认证凭据
4. 配置开机自启和看门狗

## Step 3: 记录输出信息

脚本运行完毕后会输出类似信息：

```
╔═══════════════════════════════════════════════╗
║  ✅ Setup Complete!                            ║
║                                                ║
║  PROXY_TAILSCALE_IP = 100.x.x.x               ║
║  SOCKS_USER         = gha_xxxxxxxx             ║
║  SOCKS_PASS         = xxxxxxxxxxxxxxxxxxxxxxxx ║
╚═══════════════════════════════════════════════╝
```

**把这三个值记下来**，下一步要用。

## Step 4: 配置 GitHub Secrets

进入仓库 Settings → Secrets and variables → Actions，添加以下 secrets：

| Secret Name | 值 | 说明 |
|---|---|---|
| `TS_OAUTH_CLIENT_ID` | *见下方* | Tailscale OAuth Client ID |
| `TS_OAUTH_SECRET` | *见下方* | Tailscale OAuth Secret |
| `PROXY_TAILSCALE_IP` | `100.x.x.x` | 手机的 Tailscale IP |
| `SOCKS_USER` | `gha_xxxxxxxx` | gost 认证用户名 |
| `SOCKS_PASS` | `xxxxxx...` | gost 认证密码 |

### 获取 Tailscale OAuth 凭据

1. 打开 https://login.tailscale.com/admin/settings/oauth
2. 点击 **Generate OAuth client**
3. 勾选 **Devices → Read**（最小权限即可）
4. 添加 Tag: `tag:ci`
5. 点击 Generate → 复制 Client ID 和 Secret

> ⚠️ 需要先在 ACL 中添加 `tag:ci` 的定义。进入 https://login.tailscale.com/admin/acls/file，在 `tagOwners` 中添加：
> ```json
> "tagOwners": {
>   "tag:ci": ["autogroup:admin"]
> }
> ```

## Step 5: 手机防杀设置

**这一步非常重要！** 否则 Android 会在后台杀死 Termux。

1. **设置 → 电池/应用电池管理 → Termux → 不限制 (Unrestricted)**
2. **设置 → 电池/应用电池管理 → Tailscale → 不限制 (Unrestricted)**
3. **最近任务列表 → 长按 Termux 卡片 → 点 🔒 锁定**
4. 在 Termux 中运行 `termux-wake-lock`（通知栏会出现常驻通知）

> 不同手机品牌的设置路径可能不同。关键是让 Termux 和 Tailscale 不被电池优化杀死。

## Step 6: 验证

### 从手机本地验证

在 Termux 中执行：

```bash
# 检查 gost 是否在运行
pgrep gost && echo "gost is running" || echo "gost is NOT running"

# 检查 Tailscale 状态
tailscale status

# 测试代理出口 IP
source ~/.gost_credentials
TAILSCALE_IP=$(tailscale ip -4)
curl -x "socks5h://${SOCKS_USER}:${SOCKS_PASS}@${TAILSCALE_IP}:1080" https://httpbin.org/ip
```

### 从 GitHub Actions 验证

手动触发 `Proxy Health Check` workflow：
1. 进入仓库 → Actions → Proxy Health Check
2. 点击 Run workflow
3. 检查日志，确认 exit IP 是你的住宅/移动 IP

---

## 故障排查

| 症状 | 排查 |
|------|------|
| GHA 报 proxy unreachable | 手机上检查 Termux 是否在运行 + `tailscale status` |
| gost 没有运行 | `bash ~/gost-watchdog.sh` 手动拉起 |
| Tailscale 断连 | `tailscale up --hostname=smartinfra-phone` 重连 |
| 手机重启后代理没自启 | 确认 Termux:Boot 已安装并且首次打开过 |
| 出口 IP 是云 IP | PROXY_SERVER 环境变量可能未正确传入，检查 workflow 日志 |

---

## 日常维护

基本无需维护。以下情况需要手动介入：

- **Tailscale 登录过期**（~180 天）：Termux 中重新 `tailscale up`
- **手机恢复出厂**：重新运行安装脚本
- **换新手机**：重新运行安装脚本，更新 `PROXY_TAILSCALE_IP` secret
