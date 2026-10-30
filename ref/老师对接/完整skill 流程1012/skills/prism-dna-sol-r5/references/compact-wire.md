# 可选compact wire传输

来源：2026-10-02 owner的只准备/解封模块，后来在30/100实验用于原R5主判。当前文件`scripts/wire_adapter.py`不执行模型；普通`scripts/cli.py`原生入口仍可用。

外层返回binding_id和normative_result_json字符串，内层仍含完整原始schema要求。validate-response核对原图/原规则/原prompt哈希，解封后交原规范与原解码器。不得补字段、改值或把空值填成已知。

```text
python -B -X utf8 scripts/wire_adapter.py --help
```

prepare需要当前实际skill-root、image、image-id、call-id和out；确切参数以--help为准。planned-command仅供本机有界执行器审阅，不是用户授权本身。原始outer、inner、validation、effective prompt/schema和receipt分别保存。旧机器的执行路径不能直接重用。

此模块的离线准备/解封检查不证明更快、更省token或视觉更准。失败保留，重试仍受当前每图预算约束；不扩大调用次数。
