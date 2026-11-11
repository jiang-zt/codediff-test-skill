# GitHub 变更分析工作流

目标：读取 GitHub 代码差异及相关上下文，按后附的统一交付规范生成中文分析文档与可实操参考的测试用例。分析由客户端模型完成，无须 clone 或准备本地项目。

## 1. 确认输入与分析场景

- PR链接提取 owner/repo 与 PR编号；只提供SHA时还需仓库，可使用用户明确配置的唯一仓库，不猜测。
- mode=review：输入 PR编号或40位完整提交SHA；mode=test：输入 base_sha、head_sha，均为用户给出的完整SHA，无默认master。
- 两种场景采用相同报告维度与用例格式；review在风险分析中补充代码评审发现，test重点说明提测影响与回归范围。
- output_dir 仅取用户在对话中明确指定的保存目录；尚未提供时可继续分析，保存前询问。

## 2. 获取 diff 与核对版本

- review调用 get_review_diff(repo, pr_number或sha)。仅ok=true且status=ready才分析；无唯一PR或SHA不是当前head时，展示候选/版本差异，等待选择，不静默改成最新PR。
- test调用 get_test_diff(repo, base_sha, head_sha)。DIVERGED_BASE时说明基线非祖先，不擅自更换基线或比较口径。
- 检查comparison_base_sha、head_sha、files、file_list_complete、complete和limitations。complete不代表patch未截断或分析覆盖完整，空diff也不代表无风险。
- GitHub认证仅通过MCP环境配置，不让用户在对话粘贴令牌，不访问未授权仓库。

## 3. 补充完整代码与依赖

- 调用 read_github_file 读取 head_sha 的完整变更方法及相关接口、测试和配置；必要时读取 comparison_base_sha 的旧代码。
- 删除文件读取comparison_base_sha；重命名旧文件使用previous_path。fork PR的head文件优先使用head_repo，该仓库也需读取授权。
- 不用本地工作区替代提测版本。Contents API可能解引用符号链接，链接本身变化需另行核对。
- 依赖路径不明确时询问，或使用客户端已有且获准的搜索能力。本MCP不提供全仓库搜索或完整跨服务调用链。
- 初轮补充最多10个文件，再根据风险决定是否扩大；文件超限、patch缺失/截断、二进制、未知依赖及未读取范围必须列明。

## 4. 对齐统一交付参数

- save_analysis_report 的mode与当前场景一致，repo=实际仓库，base_sha=comparison_base_sha，head_sha=工具返回的目标SHA。
- 不用PR目标分支当前SHA替代实际比较基线；没有准确版本证据时先报告获取失败，不伪装为完成分析。
- 使用后附的统一交付规范完成分析、用例设计与保存；不另设GitHub版输出标准。
