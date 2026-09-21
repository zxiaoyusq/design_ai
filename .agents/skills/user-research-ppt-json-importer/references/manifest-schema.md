# 导入清单格式

导入脚本接受一个 JSON 文件。路径均使用正斜杠；`image_subdir` 相对目标 JSON 所在目录。

```json
{
  "source_file": "ref/example.pptx",
  "source_language": "en",
  "translated_to": "zh-CN",
  "image_subdir": "ppt_images/user_slug",
  "records": [
    {
      "id": "ppt-s02-current-phone",
      "source_slide": 2,
      "scenario_type": "当前手机",
      "question_type": "品牌与型号",
      "question": "请展示当前使用的手机，并说明品牌和型号。",
      "answer": "当前使用 Samsung A36。",
      "images": [
        {
          "shape_path": "/6",
          "code": "PPT-S02-PHONE",
          "emotion_tag": "REFERENCE",
          "description_zh": "当前使用的手机",
          "evidence_scope": "exact"
        }
      ]
    },
    {
      "id": "ppt-s08-style-groups",
      "source_slide": 8,
      "scenario_type": "风格偏好",
      "question_type": "喜欢的风格组",
      "question": "请选择喜欢的风格组。",
      "answer": "选择 Group3。",
      "images": [
        {
          "shape_path": "/22",
          "code": "Group3",
          "emotion_tag": "ENJOY",
          "description_zh": "Group3 组合图",
          "evidence_scope": "group_composite",
          "contained_codes": ["S9", "S10", "S11", "S12"],
          "preference_codes": ["S9", "S10", "S11", "S12"]
        }
      ]
    },
    {
      "id": "ppt-s11-electronics",
      "source_slide": 11,
      "scenario_type": "电子产品偏好",
      "question_type": "喜欢的电子产品",
      "question": "请选择喜欢的电子产品。",
      "answer": "选择 E4。",
      "missing_images": [
        {
          "code": "E4",
          "emotion_tag": "ENJOY",
          "description_zh": "PPT 中选中 E4，但没有对应图片对象",
          "preference_codes": ["E4"]
        }
      ]
    }
  ]
}
```

## 字段说明

- `source_file`：写入 JSON 的项目相对来源路径。
- `image_subdir`：图片输出目录，相对目标 JSON 所在目录；只能位于 `ppt_images/` 下。
- `records`：仅放有问题且有回答的记录。
- `source_slide`：从 1 开始的 PPT 页码。
- `images[].shape_path`：图片在该页中的形状路径，例如 `/13`、`/16/0/0`。用检查脚本获得。
- `code`：写入 `ref_pic` 的图片或组合编号。
- `emotion_tag`：`ENJOY`、`DISLIKE` 或 `REFERENCE`。
- `evidence_scope`：普通原图用 `exact`，组合图用 `group_composite`。
- `contained_codes`：组合图中明确标出的子编号，仅用于追溯。
- `preference_codes`：应写入 `image_preferences` 的编号。省略时，喜欢或不喜欢图片默认使用 `code`；设为空数组可禁止生成偏好记录。
- `link_metadata`：可选对象，用于保存 `reason_codes`、排名或拥有状态等与该图直接相关的结构化信息。
- `missing_images`：PPT 有明确图片编号但缺少图片对象时使用。导入后状态为 `missing_source_image`，本地路径为空。

同一用户、同一情绪下重复出现的 `preference_code` 只生成一条偏好记录，其余出现位置作为 `ppt_evidence` 保存。
