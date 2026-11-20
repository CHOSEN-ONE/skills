# CHOSEN-ONE Skills

> 一组可安装、可复用的 Agent Skills。每个 skill 都放在独立子目录中，按需安装。

## 当前 Skills

| Skill | 用途 | 安装 |
|---|---|---|
| [chandao](chandao/README.md) | 通过 HTTP 管理禅道项目版本和测试单，按 Markdown 模板提测，同时支持任务查询、Bug 处理和工时核对补录 | `npx skills add CHOSEN-ONE/skills --skill chandao` |
| `releasego` | 查询发版、比较 GitLab 改动和跟踪 Jenkins 构建 | `npx skills add CHOSEN-ONE/skills --skill releasego` |

## 安装全部 Skills

```bash
npx skills add CHOSEN-ONE/skills
```

只安装某一个 skill：

```bash
npx skills add CHOSEN-ONE/skills --skill chandao
```

Windows PowerShell 如果提示脚本执行策略错误，请使用 `npx.cmd` 替代 `npx`。

## 目录结构

每个 skill 都是一个完整目录，至少包含 `SKILL.md`：

```text
skills/
  README.md
  chandao/
    SKILL.md
    README.md
    agents/
    references/
    scripts/
    tests/
```

## 新增 Skill

1. 在仓库根目录创建以 skill 名称命名的子目录。
2. 放入完整的 `SKILL.md` 和需要的 `references/`、`scripts/`、`tests/`。
3. 在本 README 的列表中补充用途和安装示例。
4. 发布前验证 YAML frontmatter、单元测试和真实安装结果。

## 贡献与安全

请不要提交密码、Cookie、访问令牌、登录状态文件或企业内部的个人数据。提交 Issue 或 Pull Request 时，先对账号、域名、任务内容和接口响应进行脱敏。

## License

各 skill 优先使用其目录中的 LICENSE。未单独声明时，适用仓库根目录的 LICENSE。
