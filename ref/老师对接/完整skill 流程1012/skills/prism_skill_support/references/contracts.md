# 棱镜全流程合同 4.3

这是18个分工技能、共享运行工具、提示词/字典、校验器与校准案例的完整方法包。工作流覆盖证据入库、用研/趋势语义、H01、选向、原图候选、可见解析、设计情绪、ID/CMF、评审与源文件交付。它需要当前项目的真实输入和实际判断；不内置全图库或私有访谈，不是一键生成审美结论的软件。

## 当前规则与历史兼容

用户最新指令优先。当前项目总体风格层、视觉+解析、保留用研语义、每板至少8张原图、不重绘、不硬凑、DINO停止。人物/服装/家居可进入，跨品类有价值但无硬配额；没有通用秀场百分比、固定Top5、固定方形网格或“必须几维”的得分门槛。规则与反馈版本见`prism-visual-family`。

旧两侧语义、H01、冻结R5和原生Quality/H2算法随包，保持原格式及适用范围。新总体风格路径用[风格成板合同](style-board-contract.md)；需要原生兼容时才读[native-v2-contracts](native-v2-contracts.md)及各模块的字段文档。不要用旧PASS给新视觉流程背书，也不要用新板JSON假扮原生H2。

## 冻结与状态

project记录run_mode、research_level、design_question、input_paths、selection、candidate_pool_policy、quantity_policy、source_policy、image_policy、model_policy、execution_authorization及输出目录。迁移配置相对路径以配置文件目录为准。运行FileRef用当前绝对路径与真实sha256；便携包可先用包内相对路径，解压后按字节校验重绑，原记录不覆盖。

状态分列semantic、visual/style、presentation、quantity/provenance、native_gate、user_feedback。作者自审、独立AI、设计师反馈和真实被访谈人选择各记实际身份/版本；pending/not_executed不能填pass。无材料时交缺口，不造原文、素材、选择确认或模型回执。

## 阶段交接

1. 用研：源文件/页码/shape/人物/对象、原文全文、角色与正反态度，准确引文及全部覆盖账本。字节去重不丢人图关系；报告摘要不冒充逐字访谈。
2. 趋势：完整文章目录、原文或source_paraphrase、主/次语义归属、图片关联旁表、未知与覆盖。库内规模排名不是市场潜力。
3. H01：双侧具体依据、共同原则、档位、每条负向逐方向审计与未决；选向记录真实actor，不固定方向数。
4. 原图：展开选中方向有界候选，原语义绑定不丢。用户授权的补库单列视觉延展，不能自动成为旧趋势簇成员。每层实际处理分母可追溯。
5. 解析与视觉：已有DNA保留known/partial/pending/invalid；当前原图观察单列。词或算法相近不等于设计情绪一致；看形体、色材、构造如何共同成立，反证不能被平均分消解。
6. 成板：逐图与最大差异对复核，多类素材不硬凑；至少8张去重来源原图。纯图版可独立判断，沟通版有短说明。具体要求见[成板](style-board-contract.md)、[评审](review-contract.md)、[交付](delivery-contract.md)。

执行与模型见[execution](execution.md)，阶段路由见[routing](routing.md)，选材工具见[material-contract](material-contract.md)。调用工具前查看对应`--help`与本技能说明；不由安装触发模型、下载、发布或额外线程。
