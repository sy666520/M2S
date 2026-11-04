# 桌面版 & 变现体系

## 现状一句话

**当前是全功能免费，商业模式整体处于关闭状态**。但广告位、免费额度、激活码买断的代码和界面都已就绪并测试通过，后续想收费，把一个开关打开即可，不需要再写代码。

## 日常启动

```bash
py -3.10 desktop/app.py          # 打开桌面窗口（推荐）
py -3.10 desktop/app.py --debug  # 带开发者工具调试
```

也可以继续用浏览器方式（`uvicorn backend.main:app --port 8173`），同一套界面。

## 商业模式开关

配置在 **`data/billing.json`**：

```json
{ "enabled": false }
```

| enabled | 行为 |
|---|---|
| `false`（当前） | 全功能免费：不限转谱次数、不显示推广位、不弹任何付费窗口。徽标显示「全功能免费」 |
| `true` | 免费额度 2 次/天 + 看推广解锁 3 次/次（每天最多 3 次）+ 激活码买断不限次 |

改完保存即生效（按文件修改时间热加载，不用重启）。设环境变量 `M2S_BILLING=1` 也能强制开启。

开启后相关接口自动生效：

| 接口 | 作用 |
|---|---|
| `GET /api/license` | 额度与激活状态 |
| `POST /api/license/redeem` | 激活码兑换 |
| `POST /api/license/ad/start` | 开始「看推广」计时，返回 12 秒会话 |
| `POST /api/license/ad/claim` | 看满后领取 +3 次 |
| `GET /api/ads?slot=banner\|unlock` | 取推广素材 |
| `POST /api/ads/event` | 曝光/点击上报 |
| `GET /api/ads/stats` | 对账数据 |

## 想收费时怎么做（三步）

1. **打开开关**：`data/billing.json` 的 `enabled` 改 `true`。
2. **生成激活码卖给用户**：
   ```bash
   py -3.10 tools/gen_key.py --count 20        # 批量 20 个通用码
   py -3.10 tools/gen_key.py --bind            # 绑定当前这台机器
   py -3.10 tools/gen_key.py --machine AB12-CD34-EF56   # 绑定用户的机器码
   ```
   码里的 6 位序号就是订单号，发货记录存一份即可售后。码是 HMAC 离线校验的，
   **激活过程完全不需要联网**。
3. **换上真实推广素材**：编辑 `desktop/ads/ads.json`（文案、跳转链接、图片），
   或设置环境变量 `ADS_REMOTE_URL` 指向一个远程 JSON，随时换素材不用重新发包。

对账：`GET /api/ads/stats` 返回每个推广位的曝光/点击计数，落地在
`data/ads_stats.json`，按周导出发给广告主。

## 激活码的安全性边界（说实话）

- 签名密钥经环境变量 `M2S_LICENSE_SECRET` 配置，**不写在代码里**——源码仓库
  可以公开，没密钥的人生成不出有效激活码（未配置时激活功能自动禁用，不影响免费额度）。
  打包发布时把密钥编译进安装包，理论上仍可被逆向出算法。
  对几十元量级的工具这是行业通行做法（AnthemScore 同样可被破解）；
  真正的防线是**持续更新**——换版本时改 `_KEY_VERSION`，旧码全部作废。
- 伪造或错字符的码会直接被拒（有测试覆盖），但挡不住持有密钥的人生成有效码。
- 如果未来收入规模到了值得认真防盗版，再上在线校验服务器，接口已留好。

## 广告位形式说明（为什么不是广告联盟）

Windows 桌面没有正规广告联盟（穿山甲/优量汇/AdMob 只对移动端开放），
市面上的桌面弹窗联盟多为灰产，会被杀毒误报。所以这里的推广位是**自营**的：
素材自己放，广告主自己谈（琴行、乐器店、音乐培训、乐谱打印…），
按月卖位，收入归自己。前端会按 `weight` 加权随机展示。

## 打包成单文件 EXE

```bash
py -3.10 -m pip install pyinstaller
py -3.10 -m PyInstaller desktop/app.py --name music2score --onedir --noconsole
```

注意事项：

- `--onedir` 而不是 `--onefile`：torch + CUDA 依赖约 3~4 GB，onefile 每次启动
  都要解压到临时目录，会慢到不可用。
- 打包后首次启动要让 PyInstaller 收集 `torch`/`demucs` 的动态库，可能需要
  在 spec 里加 `collect_dynamic_libs("torch")`。
- WebView2 运行时 Win10/11 自带，无需分发。
- 如果嫌安装包太大，备选方案：安装包只含 CPU 版 torch（约 300 MB），
  首次启动检测到 NVIDIA 显卡时提示「下载 GPU 加速包（约 2.5 GB）」。
