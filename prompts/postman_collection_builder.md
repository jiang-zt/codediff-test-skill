# Postman 集合生成

## 目标

根据已识别的 Java/Spring Controller 接口生成可导入 Postman 的集合草稿。Postman 资产是辅助测试资产，不替代中文测试影响分析报告。

## 推荐工具

```bash
python3 tools/postman_builder.py \
  --impact-json output/<featureID>/impact.json \
  --output output/<featureID>/postman_collection.json
```

可指定 base URL 变量名：

```bash
python3 tools/postman_builder.py \
  --impact-json output/<featureID>/impact.json \
  --output output/<featureID>/postman_collection.json \
  --base-url-var base_url
```

## 生成规则

- 只包含从 Controller 证据中识别到的接口，或用户明确确认的接口。
- 默认使用 `{{base_url}}`。
- 鉴权使用占位符，不写入真实 token、cookie 或密钥。
- 请求体无法确认时使用占位 JSON，并标注待补充。
- 基础断言可以包括状态码 2xx、响应时间阈值。
- 业务断言无法确认时不要编造。

## 人工补充项

Postman 集合通常仍需人工补充：

- 鉴权 header。
- 租户、机构、环境 header。
- 测试数据 ID。
- 请求体真实字段。
- 成功和失败业务断言。
- 文件上传、multipart、签名、加密参数。

## 资产关卡 Harness（关卡检查）

生成后检查：

```text
□ JSON 可解析
□ 文件已写入 output/<featureID>/postman_collection.json，除非用户指定了其他目录
□ item 数量与识别接口数量一致，除非已说明过滤原因
□ 未包含未识别、未确认的接口
□ 未写入真实密钥或 token
□ 请求体和断言中的未知内容使用占位符
```
