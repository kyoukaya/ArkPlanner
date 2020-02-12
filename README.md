# arkplanner-api

Hosted instances available at https://ark.kyou.dev/plan and https://ak.kyou.dev/plan.

arkplanner-api is an API focused fork of ycremar's [ArkPlanner](https://github.com/ycremar/ArkPlanner) with an added emphasis on catering to non-Chinese servers.

ArkPlanner is a tiny python program for the mobile game Arknights. The variety of items dropping at different stages and complicated crafting system make it difficult to create the most efficient plan to obtain items. ArkPlanner helps you to make the optimal plan for any given combinations of the required item based on open-sourced stats data and items synthesize rules, and linear programming algorithms.

## API

The only endpoint available is the `/plan` endpoint.

```js
{
    // The only required field, 'required' must have a length > 1.
    // Keys may be either one of a properly formed item name in EN/CN/JP/KR,
    // case sensitive, or an item's ID. The type of key must be consistent.
    "required": "{ string: integer } !required",
    // Items already owned by the user, key parsing is the same as used in 'required'
    // default: {}
    "owned": "{ string: integer }",
    // Output language, will match language used in required if not specified.
    // default: "en"
    "out_lang": "string",
    // Consider crafting byproducts
    // default: false
    "extra_outc": "bool",
    // Compatibility mode for non Chinese servers (EN/JP/KR) to only consider
    // content that is available to them.
    // default: false
    "non_cn_compat": "bool",
    // A list of stage codes to ignore.
    // default: []
    "exclude": "list[string]",
    // default: false
    "exp_demand": "bool",
    // default: true
    "gold_demand": "bool",
}
```

## Deployment
----

Deployable on Heroku, albeit rather slow. TODO: Heroku deploy instructions.

## 鸣谢 - Acknowledgement

数据来源：

- 明日方舟企鹅物流数据统计 [penguin-stats.io](https://penguin-stats.io/)

- 明日方舟工具箱 [ak.graueneko.xyz](https://ak.graueneko.xyz/)
