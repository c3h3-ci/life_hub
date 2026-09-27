# Life Hub 🏪 — 生活服务集成

[![GitHub](https://img.shields.io/badge/GitHub-C3H3--AI%2Flife__hub-blue)](https://github.com/C3H3-AI/life_hub)
[![HA Integration](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-orange)](https://github.com/C3H3-AI/life_hub)

Home Assistant 自定义集成，聚合多个中国生活服务平台，统一 API 接口。

**设计理念**：一个集成入口，通过子条目（subentry）插拔式添加任意数量的服务账号。每个服务一个工具入口，通过参数区分用途。

---

## 📋 支持的服务

| 服务 | Provider Key | 认证方式 | 传感器 |
|------|-------------|---------|--------|
| 🍔 **一鸣真鲜奶吧** | `yiming` | 手机号+验证码 | 17 个（余额/积分/优惠券/订单等） |
| 🍟 **麦当劳** | `mcdonalds` | MCP Token | 7 个（积分/优惠券/活动/订单） |
| 🛵 **美团** | `meituan` | API Token | 2 个（优惠券数/订单数） |
| 🏨 **美团旅行** | `meituan_travel` | API Token | 1 个（连接状态） |
| ✈️ **飞猪旅行** | `fliggy` | API Key | 1 个（连接状态） |
| 🚄 **携程旅行** | `ctrip` | API Token | 1 个（连接状态） |
| 🚕 **滴滴出行** | `didi` | MCP Key | 1 个（连接状态） |
| 🌤️ **百度地图** | `baidu_map` | API Key | 5 个（温度/天气/湿度/风力/风向） |
| 🗺️ **高德地图** | `gaode` | API Key | 1 个（连接状态） |
| 🎵 **音乐** | `music` | API Key/Cookie | 1 个（连接状态） |

---

## 🚀 安装

### HACS 安装

1. 在 HACS 中添加自定义仓库：`C3H3-AI/life_hub`
2. 搜索 "Life Hub" 并安装
3. 重启 Home Assistant

### 手动安装

```bash
git clone https://github.com/C3H3-AI/life_hub.git
cp -r life_hub/custom_components/life_hub /path/to/ha/config/custom_components/
# 重启 HA
```

---

## ⚙️ 配置

1. **设置 → 设备与服务 → 添加集成** → 搜索 "Life Hub"
2. 创建集成实例后，点击 **添加子条目** 选择服务
3. 根据提示填写凭证（API Token / 手机号 / API Key 等）
4. 添加成功后自动重载，传感器与服务即可使用

### 默认地址（可选）

在 **Life Hub → 选项** 中可设置默认地址：
- 支持完整地址：`广东省深圳市福田区XX花园X栋X单元`
- 支持经纬度：`22.543,114.057`
- 留空则使用 HA 系统位置

该地址会用于：
- 🌤️ 百度天气查询
- 🍔 一鸣查找最近门店
- 🍟 麦当劳/美团下单时自动填充配送地址

### Token 获取指南

| 服务 | Token 获取地址 | 配置指南 |
|------|---------------|---------|
| 一鸣真鲜奶吧 | 手机号+验证码（无需预申请） | — |
| 麦当劳 | [open.mcd.cn/mcp](https://open.mcd.cn/mcp) | [QClaw 指南](https://qclaw.qq.com/docs/215059947716583424) |
| 美团 | [developer.meituan.com](https://developer.meituan.com/zh/v2/dev/token) | [QClaw 指南](https://qclaw.qq.com/docs/210805139605942272.html) |
| 美团旅行 | [developer.meituan.com](https://developer.meituan.com/zh/v2/dev/token) | — |
| 飞猪旅行 | [flyai.open.fliggy.com](https://flyai.open.fliggy.com/) | — |
| 携程旅行 | [t.ctrip.cn/28J6RhL](http://t.ctrip.cn/28J6RhL) | [QClaw 指南](https://qclaw.qq.com/docs/208231741261246464) |
| 滴滴出行 | [mcp.didichuxing.com](https://mcp.didichuxing.com/) | — |
| 百度地图 | [lbs.baidu.com/apiconsole/agentplan](https://lbs.baidu.com/apiconsole/agentplan) | [QClaw 指南](https://qclaw.qq.com/docs/212966665410375680) |
| 高德地图 | [console.amap.com/dev/key/app](https://console.amap.com/dev/key/app) | — |
| 音乐 | [QClaw 指南](https://qclaw.qq.com/docs/214847013744275456) | — |

---

## 🔧 服务调用规范

所有服务遵循统一命名格式：**`life_hub.{provider}_call_tool`**

### 通用参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tool` | string | ✅ | 选择要调用的功能 |
| `params` | object | ❌ | 功能参数（依 tool 而异） |
| `store` | string | ❌ | 门店中文名（麦当劳使用，自动解析为门店编码） |
| `product` | string | ❌ | 餐品名称筛选（麦当劳使用） |
| `target_device` | device | ❌ | 选择设备来指定操作哪个账号 |
| `target_entity` | entity | ❌ | 选择传感器来指定操作哪个账号 |
| `subentry_id` | string | ❌ | 直接输入子条目ID |

### 示例

```yaml
# 一鸣：查询余额
service: life_hub.yiming_call_tool
data:
  tool: get_balance

# 一鸣：领所有优惠券（倪一可的账号）
service: life_hub.yiming_call_tool
data:
  tool: receive_all_coupons
  target_device: "device_id..."

# 一鸣：批量领所有账号的券
service: life_hub.yiming_call_tool
data:
  tool: claim_all

# 麦当劳：查可用优惠券
service: life_hub.mcdonalds_call_tool
data:
  tool: available-coupons

# 麦当劳：查餐品价格（自动解析门店名）
service: life_hub.mcdonalds_call_tool
data:
  tool: query-meals
  store: "福田高铁站"
  params:
    beType: 1
    orderType: 1

# 麦当劳：自动领券
service: life_hub.mcdonalds_call_tool
data:
  tool: auto-bind-coupons

# 滴滴：预估价格
service: life_hub.didi_call_tool
data:
  tool: taxi_estimate
  params:
    from_name: "深圳北站"
    to_name: "深圳宝安机场"

# 滴滴：搜索地点
service: life_hub.didi_call_tool
data:
  tool: maps_textsearch
  params:
    keywords: "天安门"
    city: "北京"

# 百度地图：搜索POI
service: life_hub.baidu_map_call_tool
data:
  tool: search_poi
  params:
    query: "天安门"
    region: "北京"

# 美团：查优惠券
service: life_hub.meituan_call_tool
data:
  tool: get_coupons

# 美团旅行：规划行程
service: life_hub.meituan_travel_call_tool
data:
  tool: plan_itinerary
  params:
    city: "杭州"
    days: 3
```

---

## 📡 传感器

### 状态传感器（所有服务都有）

每个已配置的子条目都会创建一个状态传感器：
```
sensor.<provider>_连接状态 → "connected" / "disconnected"
```

### 数据传感器（部分服务）

#### 🍔 一鸣真鲜奶吧（17 个）

| 传感器 | 说明 |
|--------|------|
| `sensor.<key>_余额` | 储值余额 |
| `sensor.<key>_会员姓名` | 会员姓名 |
| `sensor.<key>_会员等级` | 会员等级 |
| `sensor.<key>_会员权益` | 会员权益层级 |
| `sensor.<key>_成长值` | 成长值 |
| `sensor.<key>_会员到期日` | 会员到期日 |
| `sensor.<key>_积分` | 当前积分 |
| `sensor.<key>_优惠券汇总` | 优惠券总张数 |
| `sensor.<key>_可用优惠券` | 可用优惠券张数 |
| `sensor.<key>_可领优惠券` | 可领优惠券张数 |
| `sensor.<key>_最近订单` | 最近订单数 |
| `sensor.<key>_交易明细` | 最近交易金额 |
| `sensor.<key>_积分明细` | 最近积分变动 |
| `sensor.<key>_最近门店` | 最近门店 |
| `sensor.<key>_默认地址` | 默认地址 |
| `sensor.<key>_App公告` | App 公告 |
| `sensor.<key>_付款二维码` | 付款二维码 |

#### 🍟 麦当劳（7 个）

| 传感器 | 说明 |
|--------|------|
| `sensor.<key>_可用积分` | 可用积分 |
| `sensor.<key>_累计积分` | 累计积分 |
| `sensor.<key>_即将过期积分` | 即将过期积分 |
| `sensor.<key>_可领优惠券` | 可领优惠券数量 |
| `sensor.<key>_我的优惠券` | 我的优惠券数量 |
| `sensor.<key>_进行中活动` | 进行中活动数 |
| `sensor.<key>_进行中订单` | 进行中订单数 |

#### 🌤️ 百度地图（5 个）

| 传感器 | 说明 |
|--------|------|
| `sensor.<key>_温度` | 当前温度 |
| `sensor.<key>_天气状况` | 天气状况 |
| `sensor.<key>_湿度` | 湿度 |
| `sensor.<key>_风力` | 风力 |
| `sensor.<key>_风向` | 风向 |

#### 🛵 美团（2 个）

| 传感器 | 说明 |
|--------|------|
| `sensor.<key>_优惠券数量` | 优惠券数量 |
| `sensor.<key>_连接状态` | 连接状态 |

---

## 🛠️ 自动化示例

### 一鸣每日自动领券

```yaml
alias: 一鸣每日领券
trigger:
  - platform: time
    at: "09:00:00"
action:
  - service: life_hub.yiming_call_tool
    data:
      tool: claim_all
```

### 麦当劳自动领券

```yaml
alias: 麦当劳自动领券
trigger:
  - platform: numeric_state
    entity_id: sensor.mai_dang_lao_ke_ling_you_hui_quan
    above: 0
action:
  - service: life_hub.mcdonalds_call_tool
    data:
      tool: auto-bind-coupons
```

### 天气播报

```yaml
alias: 百度天气播报
trigger:
  - platform: time
    at: "07:30:00"
action:
  - service: tts.baidu_say
    data:
      message: >
        今天天气 {{ states('sensor.tian_qi_zhuang_kuang') }}，
        温度 {{ states('sensor.wen_du') }}°C
```

---

## 🔄 多账号支持

同一服务可以添加多个子条目（如倪一可+陈朵朵两个一鸣账号）：

```yaml
# 操作陈朵朵的账号（选择设备）
service: life_hub.yiming_call_tool
data:
  tool: get_balance
  target_device: "device_id..."
```

```yaml
# 领所有账号的优惠券
service: life_hub.yiming_call_tool
data:
  tool: claim_all
```

---

## 📁 项目结构

```
custom_components/life_hub/
├── __init__.py          # 集成入口，管理 HubRuntime
├── config_flow.py       # 配置流程
├── provider_flow.py     # 子条目流程（添加/编辑/删除）
├── sensor.py            # 传感器创建
├── services.py          # 服务注册（统一 _call_tool 命名）
├── services.yaml        # 服务 UI 定义
├── models.py            # 数据模型
├── const.py             # 常量
├── manifest.json
├── translations/        # 中英翻译
├── brand/               # 品牌图标
└── providers/           # 服务提供商
    ├── registry.py      # 注册表
    ├── base.py          # ProviderSpec 基类
    ├── base_client.py   # MCP 客户端基类
    ├── yiming/          # 一鸣真鲜奶吧
    ├── mcdonalds/       # 麦当劳
    ├── meituan/         # 美团
    ├── meituan_travel/  # 美团旅行
    ├── didi/            # 滴滴出行
    ├── fliggy/          # 飞猪旅行
    ├── ctrip/           # 携程旅行
    ├── baidu_map/       # 百度地图
    ├── gaode/           # 高德地图
    └── music/           # 音乐
```

---

## ⚠️ 注意事项

1. **Token 安全**：部分 API Token 有调用次数限制，请合理使用
2. **多账号**：同一服务可添加多个子条目，服务调用时通过 `target_device` / `subentry_id` 区分
3. **服务命名**：所有服务统一为 `{provider}_call_tool`，参数统一为 `tool` + `params` + 辅助字段
4. **传感器自动刷新**：领券/下单等操作后，关联传感器会自动刷新（无需等待30分钟周期）
5. **频率限制**：部分上游 API 有调用频率限制（如滴滴每5小时1000次）
6. **默认地址**：在集成选项中设置的地址会自动用于配送和天气查询

---

## 📄 License

MIT
