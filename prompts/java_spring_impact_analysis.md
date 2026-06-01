# Java/Spring 影响面分析

## 目标

基于 `diff.json`、本地 Java/Spring 项目代码，以及可选的 PRD / 需求 / 接口文档，识别 PR 对接口、业务逻辑、DTO、数据库访问、配置、依赖和测试覆盖的影响，生成统一证据底稿 `impact.json`。

## 核心原则

`diff.json` 只说明“改了什么”；本地项目代码用于判断“影响什么”。

如果本地项目路径可用，必须结合完整文件上下文分析。不要只看 patch 就直接下结论。

如果用户提供了 PRD、需求文档或接口文档，应将文档中的业务规则、验收标准和接口契约作为可选证据源；未提供文档时，不阻塞分析，但需要记录边界。

## 推荐工具

只有 patch 上下文时：

```bash
python3 tools/java_spring_analyzer.py \
  --diff-json diff/<featureID>/diff.json \
  --output output/<featureID>/impact.json
```

有本地项目路径时：

```bash
python3 tools/java_spring_analyzer.py \
  --diff-json diff/<featureID>/diff.json \
  --repo-root . \
  --output output/<featureID>/impact.json
```

工具输出是初步分析结果。agent 需要继续阅读本地代码，补充工具无法识别的调用链、业务语义和不确定项。

如果当前目录不是用户项目根目录，将 `--repo-root .` 替换为实际项目根目录路径，并仍优先把产物写入该项目根目录的 `output/<featureID>/`。

执行前确保目录存在：

```bash
mkdir -p "output/<featureID>"
```

## 本地代码阅读顺序

按 diff 命中的文件类型阅读：

1. Controller / API
   - 读取完整 Controller。
   - 识别类级和方法级 `@RequestMapping`、`@GetMapping`、`@PostMapping` 等注解。
   - 记录接口路径、HTTP 方法、handler 方法、请求 DTO、响应类型。
2. DTO / Form / VO / Request / Response
   - 读取字段、类型、默认值、校验注解。
   - 关注新增字段、删除字段、字段类型变化、必填规则变化。
3. Service / ServiceImpl
   - 读取变更方法完整上下文。
   - 识别业务分支、事务、异常处理、外部调用、幂等和状态流转。
   - 尝试从 Controller、定时任务、消息消费者或其他 Service 找调用方。
4. Mapper / DAO / Repository / MyBatis XML
   - 读取 SQL、查询条件、结果映射、写操作。
   - 关注空结果、多行结果、分页排序、历史数据兼容和事务一致性。
5. Entity / Domain / Migration
   - 关注字段结构、枚举、序列化、数据库兼容性。
6. Config / Dependency
   - 读取 `application.yml`、`bootstrap.yml`、配置类、`pom.xml`、`build.gradle`。
   - 关注启动风险、环境差异、配置覆盖、依赖冲突和运行时兼容。
7. Existing Tests
   - 读取相关 `src/test`、`*Test.java`、`*IT.java`。
   - 判断已有测试是否覆盖本次变更。

## 文档对齐规则

如果提供了 PRD、需求文档或接口文档，按以下方式对齐：

- Controller 接口变更：对照接口文档中的路径、方法、请求参数、响应结构和错误码。
- DTO 变更：对照 PRD 或接口文档中的字段说明、必填规则、格式、枚举、默认值。
- Service 变更：对照业务规则、主流程、分支流程、异常流程和验收标准。
- Mapper / Repository 变更：对照数据查询、写入、历史数据兼容和统计口径。
- 配置 / 依赖变更：对照需求中的环境、开关、灰度、外部依赖和部署要求。

文档和代码不一致时，不要自行判断谁正确，应写入不确定项。

## 文件分类规则

| 变更类型 | 典型信号 | 测试影响 |
|---|---|---|
| Controller/API | `@RestController`、`@Controller`、Mapping 注解 | 直接接口测试和邻近接口回归 |
| DTO/Form/VO | `DTO`、`Req`、`Request`、`Resp`、校验注解 | 参数校验、兼容性、边界值 |
| Service | `Service`、`ServiceImpl`、业务方法变化 | 主流程、分支、异常、事务 |
| Mapper/DAO/Repository | MyBatis XML、`Mapper.java`、`Repository` | 查询、写入、数据一致性 |
| Entity/Migration | `Entity`、领域对象、迁移脚本 | 历史数据、序列化、字段兼容 |
| Config | `application.yml`、`bootstrap.yml`、配置类 | 启动、环境、灰度、回滚 |
| Dependency | `pom.xml`、`build.gradle` | 构建、依赖冲突、运行时兼容 |
| Tests | `src/test`、`*Test.java`、`*IT.java` | 覆盖充分性和缺失场景 |

## impact.json 要求

`impact.json` 应包含：

```json
{
  "source": {},
  "summary": {},
  "files": [],
  "apis": [],
  "dto_changes": [],
  "risks": [],
  "requirement_context": {},
  "uncertainties": []
}
```

关键字段说明：

- `files`：变更文件分类、状态、增删行、变更方法。
- `apis`：接口方法、路径、Controller、handler、请求/响应 DTO、证据。
- `dto_changes`：字段、类型、校验注解、兼容性风险。
- `risks`：按 Controller、Service、Mapper、配置、依赖等分类的测试风险。
- `requirement_context`：可选字段，记录文档来源、验收标准、接口契约、字段规则和文档/代码不一致项。
- `uncertainties`：无法从静态代码确认的内容。

## 影响面关卡 Harness（关卡检查）

生成或补充 `impact.json` 后检查：

```text
□ 每个 diff 文件都完成分类
□ impact.json 已写入 output/<featureID>/impact.json，除非用户指定了其他目录
□ Controller 变更已尝试识别接口路径和 handler
□ Service 变更已尝试查找调用方或入口
□ DTO 变更已检查字段和校验注解
□ Mapper/Repository 变更已检查数据访问风险
□ 配置和依赖变更没有被跳过
□ 已有测试变更已用于判断覆盖情况
□ 如提供文档，已将文档验收标准和接口契约与代码变更对齐
□ 如未提供文档，已记录“未提供需求/接口文档”的分析边界
□ 无法确认的调用链、鉴权、测试数据、动态路径已写入 uncertainties
```
