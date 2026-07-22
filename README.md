# Mythos 5 Burning Art（Mythos 5 焚诀）

这是一套面向能力较弱编码模型的强制工作流，不宣称它们因此与 Fable 5 / Mythos 5 等同。它把相关做事哲学拆成可执行范式：证据优先、显式未知、盲点扫描、多方案比较、独立质疑、人类计划审批、受控实施、循环工程、独立验证、计划与实际对账，以及面向人的解释与理解检查。

Fable 5 与 Mythos 5 在本套件中视为同一模型的不同称法；“Mythos 5”指解除部分安全限制的 Fable 5。套件不会复制或放宽这种安全状态，也不会绕过 Codex、Claude Code、VS Code、操作系统或组织策略的原生安全边界。

## 为什么同时使用 Rules 与 Skills

本套件采用推荐的混合结构：

- `AGENTS.md`、`CLAUDE.md` 与 `.claude/rules/` 是常驻总规，负责强制路由、13 阶段生命周期、审批门禁和不可选择性跳过。
- 九个 Skills 负责发现、未知分析、选项、计划、构建、调试、修复、验证和解释等专门动作。
- 独立 critic 与 verifier 必须使用宿主可观察的无继承上下文。Hook 先在 PreToolUse 绑定一次性的中立启动请求与封存包：Codex 的 spawn 输入必须显式带 `fork_turns="none"`；Claude Code 必须使用具名自定义 Agent，不能使用 `fork`。随后还必须匹配新的 agent ID 与独立的嵌套子代理 transcript；任一证据缺失都会拒绝 PASS，避免把同一思维链中的自我批判伪装成独立审查。
- 确定性 Hooks 负责状态、审批摘要、变更范围和 DONE 门禁；宿主原生权限与沙箱仍然优先。

## 目录

```text
Mythos 5 Burning Art/
├─ README.md                         中文使用说明
├─ spec/                             生命周期、策略与 JSON Schema
├─ src/shared/skills/                九个英文 Skills 的唯一源
├─ src/shared/runtime/               Python 标准库运行时
├─ src/codex/                        Codex 插件源
├─ src/claude/                       Claude Code 插件源
├─ repo-kits/                        可逆的仓库级 Rules 适配器
├─ dist/                             生成后的宿主插件包
├─ marketplaces/                    两个本地 Marketplace
├─ scripts/                          构建、预检、安装、卸载与验证
├─ tests/                            单元、并发和端到端契约测试
└─ evals/                            行为场景与评估结果
```

除本文件外，套件交付文件均为纯英文。

## 前置要求

- Python 3.11 或更高版本，只使用标准库，无需 `pip install`。
- 当前稳定版 Codex 或 Claude Code；VS Code 扩展应与相应 CLI 使用同一配置与插件环境。
- 每个受治理仓库都应安装仓库适配器。
- Codex 中必须显式审查并信任插件 Hooks。

先运行预检：

```powershell
python scripts/preflight.py --host both
```

若使用 `--skip-write-probe`，输出会把状态目录检查明确标记为 `skipped: true`；这只能验证结构与可执行文件发现，不能证明运行时状态目录可写。

在 macOS 或 Linux 上将 `python` 换成可用的 `python3`。

## 安装 Codex 插件

在套件根目录之外也可使用绝对路径：

```powershell
codex plugin marketplace add "<suite-root>\marketplaces\codex"
codex plugin add mythos-5-burning-art@mythos-5-burning-art-local
```

开启一个新任务，在 Codex 中运行 `/hooks`，审查并信任本插件的精确 Hook 定义。Hook 被修改后必须重新审查。不要使用跳过 Hook 信任的危险启动参数作为日常配置。

## 安装 Claude Code 插件

```powershell
claude plugin marketplace add "<suite-root>\marketplaces\claude" --scope user
claude plugin install mythos-5-burning-art@mythos-5-burning-art-local --scope user
```

运行 `/reload-plugins` 或开始新会话。插件配置中的 `python_executable` 必须指向 Python 3.11+；Windows 推荐填写 `python.exe` 的绝对路径，macOS/Linux 可使用可解析的 `python3` 或绝对路径。

本地免安装验证也可以使用：

```powershell
claude --plugin-dir "<suite-root>\dist\claude\mythos-5-burning-art"
```

## 为仓库安装常驻 Rules

安装器默认只预览，不写入：

```powershell
python scripts/install_repo_adapter.py --repo "<repo>" --host codex
python scripts/install_repo_adapter.py --repo "<repo>" --host codex --apply

python scripts/install_repo_adapter.py --repo "<repo>" --host claude
python scripts/install_repo_adapter.py --repo "<repo>" --host claude --apply
```

Claude 仓库适配器会复用并安装共享的 `AGENTS.md` 总规，再安装 `CLAUDE.md` 与 Claude Rules；Claude 专用子代理由插件包提供。Codex 仓库适配器另外安装只读 critic/verifier 定义。安装器在首次内容修改前先落盘仓库相对路径的事务清单；所有文件与清单写入使用同卷临时文件加原子替换，双宿主共用操作系统级跨进程锁，进程崩溃会自动释放锁。失败时按精确原字节自动回滚，未完成的回滚或卸载可以续跑。它拒绝 symlink、junction、reparse point 和仓库越界目标，从不覆盖不一致内容。每个宿主都有独立、可转移所有权的安装清单，可同时安装并按任意顺序卸载。

## 实际使用流程

对 build、debug、repair、重构、迁移、配置、测试或其他实质性任务，模型必须从 `mythos-orchestrate` 进入并完整走完 13 阶段，不能挑选方便的阶段。

1. 模型先做只读发现、未知分类、盲点扫描、方案比较和验收标准。
2. 模型先输出 `MYTHOS_REVIEW_PACKET_V1`；Hook 封存这份计划材料、记录内容级项目指纹并返回 `review_packet_hash`。
3. 得到该 hash 后，模型才能启动新的只读 mythos-plan-critic。Hook 会把完整封存包注入干净上下文；critic 必须返回唯一 verdict 与 MYTHOS_CRITIC_RECEIPT_V1 结构化 JSON。PASS 时阻断项、高风险项和上下文污染数组必须为空；不能在原上下文里自我批判，也不能审查另一份计划。
4. critic 通过后，模型展示最终计划，并输出带同一 hash 的 `MYTHOS_APPROVAL_BUNDLE_V1`。任何计划字段变化都会导致绑定失败。
5. Hook 对计划、范围、验收标准、独立评审、仓库/工作树身份和基线统一计算 bundle hash，然后显示唯一有效的审批语句。
6. 你若要修改计划，直接回复意见；模型必须重新规划、重新封存 review packet 并重新启动 critic。
7. 只有当你审查满意后，原样粘贴 Hook 给出的：

```text
APPROVE MYTHOS RUN <run-id> BUNDLE <bundle-hash>
```

8. 审批有效后，模型才可调用 build、debug 或 repair Skill。超出已批准路径或精确命令的动作会被拒绝；以 `/` 或 `\` 结尾的路径才递归授权目录，其他路径只授权精确目标。只要范围中包含精确命令，Hook 就会把 `node_modules`、`coverage`、`build` 和缓存等常见生成目录也纳入批准、动作和验证快照；命令造成的每个文件变化仍必须属于批准路径。动作结算时一旦发现越界文件，Hook 会记录违规、撤销审批并回到第三阶段；越界内容必须先还原，不能被下一次审批“洗成”新基线。外部系统、Git 元数据、权限、链接与纯目录变更不在可执行范围内。新的实质性人类指令会使当前审批失效。宿主原生权限仍可能再次询问你；同一次工具调用的 `PermissionRequest` 必须与 `PreToolUse` 的工具名、输入哈希及宿主提供的调用 ID 完全匹配，并且 Hook 的中性放行不会替你批准宿主权限。若人或原生策略拒绝执行，模型必须把同一待结算动作记录为 `FAIL`，明确工具没有运行。
9. 实施后，模型先输出 `MYTHOS_VERIFICATION_PACKET_V1`。Hook 检查审批、每项计划步骤与验收证据、逐项对账和当前内容指纹；最终范围、清单以及 UTF-8/Base64 的精确前后字节内容由 Hook 自己生成，封存后返回 `verification_packet_hash`。
10. 得到该 hash 后，模型才可启动新的只读 mythos-verifier。Hook 会把完整验证包注入干净上下文；verifier 必须返回唯一 verdict 与 MYTHOS_VERIFIER_RECEIPT_V1 结构化 JSON，逐项覆盖全部验收标准，并明确审批仍有效、范围一致、无阻断/高风险/污染。实施者不能验证自己，也不能让 verifier 顺手修代码；封存后任何工作区变化都会使旧回执失效。每个封存包只有一次不可覆盖的终局审查结果：无效或非 PASS 会永久拒绝该包，不能再启动另一个审查者用 PASS 覆盖，必须生成新包。
11. 通过对账、解释和理解检查后，模型输出带同一验证 hash 的 `MYTHOS_COMPLETION_BUNDLE_V1`；Stop Hook 会重算绑定、再次检查当前指纹和验收覆盖、消费审批，并且只有在全部证据与 13 阶段都成立时才允许 DONE。

当模型确实想不清楚且问题会影响结果时，它必须向人提问，而不是猜测。每次最多五问，按 `1` 至 `5` 编号；每问使用加粗的决策标题，并以三空格缩进的项目符号依次写明“为什么重要”“证据或不确定性”、A、B、C、D 与“未回答时如何处理”。A 的推荐方案标题必须加粗，A–C 必须用破折号说明收益与代价；除 A–D 字母及协议标记外，标题、标签、选项和解释都跟随用户当前语言。等待回答的整条消息只能包含这些问题块、块间空行和最后一行 `MYTHOS_WAITING_FOR_HUMAN_V1`；开场白、状态说明、尾注、错序、漏项或重复选项都会被 Hook 拒绝。


## 可执行范围

本套件的可移植运行时只执行并核验受治理项目内的普通文件内容变化。`external_effects` 必须为空；部署、远程发布、数据库或服务写入、Git index/commit/branch、权限或时间戳、symlink/hardlink/junction 和纯目录变化都会被拒绝。它也不包含审批前的可执行原型运行器；此时只能使用不改文件的参考比较，或按阶段 4 的严格 N/A 证据停止并请求单独受治理的实验环境。

`debug` 支持两种形式：需要修复时审批明确文件范围；只做诊断时可保持路径和步骤 surface 为空，但仍须审批精确诊断命令、记录每次实验，并以空内容差异完成独立验证。

## Loop Engineering

每个可执行阶段原生采用：

```text
Discover → Hypothesize → Act → Verify → Record → Decide
```

同一假设、动作与证据快照形成 attempt fingerprint。每一次由 Hook 放行的写入或精确命令都会原子登记一个唯一待结算 act，绑定工具名、精确输入摘要和动作前范围指纹；该状态在中断或重启后仍保留。工具返回并完成必要的只读观察后，模型必须用且只能用一份 `MYTHOS_ATTEMPT_PACKET_V1` 结算该 act，才能请求下一次实质性工具、重新规划、进入等待或终止状态，或开始验证；Hook 同时记录动作后的真实范围指纹。失败指纹不得重复，连续三次失败且没有信息增益时必须停止并向人给出 A–D 决策包，或提交带具体证据和恢复条件的终止包。任何会改变目标、验收标准、架构、公共行为、数据、安全、依赖、兼容性、路径或副作用的新事实都会使审批失效并回到规划。

## 状态与可移植性

默认状态不写入项目仓库，也不绑定某个插件的私有数据目录，因此 Codex 与 Claude Code 可共享同一中立状态根：

- Windows：`%LOCALAPPDATA%\Mythos5BurningArt\State`
- macOS：`~/Library/Application Support/Mythos5BurningArt/State`
- Linux：`${XDG_STATE_HOME:-~/.local/state}/mythos-5-burning-art`

可通过 MYTHOS5_STATE_HOME 显式覆盖，但该目录必须位于受治理项目之外，避免状态文件导致审批指纹自我变化。路径、Unicode、LF、仓库身份和 worktree 身份会被规范化；事件日志使用校验链，审批收据使用 HMAC，快照使用原子写入，并使用 Windows/macOS/Linux 的操作系统级 advisory lock；进程退出后锁由系统释放，不删除锁路径，也不存在过期锁抢占窗口。

同一操作系统用户仍可直接篡改自己的文件，因此这些机制是完整性和误操作防线，不是对同用户恶意代码的安全边界。真正的安全边界仍是宿主沙箱、权限策略、Hook 信任与操作系统权限。

## 卸载与回滚

先预览，再卸载仓库适配器；若内容在安装后被修改，卸载器会拒绝删除：

```powershell
python scripts/uninstall_repo_adapter.py --repo "<repo>" --host claude
python scripts/uninstall_repo_adapter.py --repo "<repo>" --host claude --apply
python scripts/uninstall_repo_adapter.py --repo "<repo>" --host codex
python scripts/uninstall_repo_adapter.py --repo "<repo>" --host codex --apply
```

宿主插件可使用各自的插件管理命令卸载：

```powershell
codex plugin remove mythos-5-burning-art@mythos-5-burning-art-local
claude plugin uninstall mythos-5-burning-art@mythos-5-burning-art-local --scope user
claude plugin marketplace remove mythos-5-burning-art-local
```

删除状态前应先确认没有需要审计或继续的运行。本套件不会自动修改全局 Codex、Claude Code 或 VS Code 设置。

## 验证

```powershell
python scripts/build_packages.py
python scripts/validate_official.py
python scripts/validate_suite.py
python scripts/verify_evals.py
python scripts/run_contract_tests.py
```

`validate_official.py` 会自动发现当前 Codex 随附的 Skill 与插件官方校验器，调用当前 Claude CLI 的插件校验器，并生成绑定校验器、源码与发行包哈希的证据文件；缺少这些当前工具或证据过期时，整套验证会失败。

测试覆盖规范化、已跟踪/相关未跟踪内容指纹、常见生成目录的有界扫描、未出生 Git 仓库的同尺寸改写、状态完整性、审批篡改、完整封存包注入、结构化 critic/verifier 回执、矛盾 verdict、旧计划失效、新指令使审批失效、失败增量、未解决偏差、验证后变更失效、每项验收 PASS、最终范围、A–D Markdown 问询、阶段约束、三次无增益停止规则、Windows 并发锁、双宿主适配器原子写入/并发安装/事务回滚/中断续跑/junction 防护、宿主合法返回协议，以及完整的“封存计划—独立批判—人类审批—范围门禁—封存证据—独立验证—DONE”流程。

行为评测是 prompt-level 的规定事实静态冒烟夹具，不伪装成真实模型调用或真实仓库执行基准。`evals/results/responses/` 保存人工维护的确定性合规回答，结果 JSON 保存场景、回答、规则、提示模板与验证器的 SHA-256 以及评分轨迹；`scripts/verify_evals.py` 会重新核对哈希、规则和所有等待回答的严格 A–D 语法。若要评估具体模型，应另行运行真实、全新、非 fork 的代理实验并独立保存结果。

## 已知边界

- Hook 只有在插件启用、宿主支持事件、定义被信任且工具走可观察路径时才生效。独立审查要求 PreToolUse 能观察专用子代理启动请求，SubagentStop 能提供匹配的新 agent ID 与独立嵌套 transcript；否则流程会停在 `NEEDS_HUMAN_JUDGMENT`。
- 部分 hosted tools 或宿主专用路径无法被本地 Tool Hook 观察；套件不得谎称完全覆盖。
- Codex/Claude Code/VS Code 版本变化可能改变 Hook 或插件协议，应重新运行预检和验证。
- 新的实质性工作建议开启新任务；同一任务中的澄清、返工与重新审批继续复用原运行账本。
- 该套件有意以更多 Token 和更多审查换取可靠性，不以节省 Token 为目标。



