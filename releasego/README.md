# ReleaseGo Skill

用自然语言查询发版状态、比较 GitLab 代码和跟踪 Jenkins 构建。明确指定目标后，可以按发版计划更新 ReleaseGo 应用和配置。

例如，问「对比两个版本之间的 RUM 应用改动」，可以得到应用清单、关联仓库和提交差异。问「核对这个构建能否用于目标发版」，可以先读取构建、应用版本和计划状态。

## 安装

```bash
npx skills add CHOSEN-ONE/skills --skill releasego
```

Windows PowerShell 如果拦截脚本入口，使用 `npx.cmd`。

## 在新机器配置

1. 安装 Python 3.10+ 和 Git，运行 `python3 --version`（Windows 可用 `py -3 --version`）及 `git --version`。
2. 在运行 Agent 的环境中设置 `TINGYUN_USERNAME` 和 `TINGYUN_PASSWORD`，或者参考 [配置模板](config.example.json)，在安装后的技能目录内创建 `config.local.json`。确保机器能访问相关公司服务。
3. 从技能目录运行 `python3 -B scripts/releasego_doctor.py`，Windows 使用 `py -3 -B scripts/releasego_doctor.py`。

- [ ] 能连接公司网络，并拥有操作所需的系统权限。
- [ ] 使用 SSH 拉取时，已配置 SSH 密钥并验证主机密钥。Tingyun Git SSH 使用 2222 端口。
- [ ] 使用网页回退时，已准备 Chrome 和浏览器自动化环境。

| 遇到的问题 | 处理方法 |
|---|---|
| 工具报告未配置凭据 | 检查 Agent 进程是否继承环境变量，或安装目录内是否存在本地配置。 |
| GitLab 仅提供 HTTP | 经授权后，在本地将 `gitlabBaseUrl` 指向准确地址，并设置 `gitlabAllowHttp` 为 `true`。HTTP 传输未加密。 |
| SSH 无法连接 | 检查公司网络、SSH 密钥和 2222 端口配置。 |

运行范围、认证策略和写入授权见 [SKILL.md](SKILL.md)。
