# 猫猫休息提醒

每工作 30 分钟，就会有一只真猫跑出来，占满屏幕卖萌 1 分钟，提醒你起来活动一下。

现在有两只猫，各自是独立的程序，可以只装一只，也可以两只都装：

| 猫 | 程序名 | 下载 |
|---|---|---|
| 暹罗猫：从屏幕底部升起来，打哈欠、东张西望 | SiameseBreak | [Releases 里的 `v*`](https://github.com/WHXisWH/siamese-break/releases/latest) |
| 曼基康：整只猫坐在屏幕正中间，看着你、左右张望 | MunchkinBreak | [Releases 里的 `munchkin-v*`](https://github.com/WHXisWH/siamese-break/releases) |

## 同事怎么用

1. 打开上面的下载链接，下载文件名里带 `Setup` 的 exe，比如 `SiameseBreak-Setup-1.0.2.exe` 或 `MunchkinBreak-Setup-1.0.0.exe`。
2. 双击安装。安装不需要管理员权限，装完会自动运行。
   - 如果 Windows 弹出“Windows 已保护你的电脑”，点 **更多信息** → **仍要运行**。这是因为程序没有购买代码签名证书，不是病毒。
3. 程序会常驻在屏幕右下角的托盘区（猫头图标，可能要先点 `^` 展开才能看到），默认开机自动启动。

不想安装的话，也可以下载文件名里带 `Portable` 的 exe，双击直接运行。

### 猫猫出现以后

- 点一下屏幕任意位置，或按 `Esc`，猫猫就会走开。
- 不管它的话，1 分钟后会自己走。
- 猫猫走后重新开始计时 30 分钟。

### 托盘菜单（点一下猫头图标）

| 菜单 | 作用 |
|---|---|
| 下一只猫猫：xx:xx | 显示下次出现的时间 |
| 现在就召唤猫猫 | 马上看猫 |
| 暂停 1 小时 | 开会、共享屏幕、演示 PPT 之前点一下，1 小时内猫猫不会出现 |
| 开机自动启动 | 勾选后开机自动运行 |
| 兼容模式 | 如果猫猫出现时背景是黑的（看不到桌面），勾上这个，程序会自动重启 |
| 退出 | 关掉程序 |

另外，电脑从睡眠中唤醒或者解锁屏幕后，计时会重新从 30 分钟开始。

## 开发

```bash
npm install
npm start
CAT_VARIANT=munchkin npm start
```

调试时可以用环境变量缩短时间：

```bash
CAT_INTERVAL_SECONDS=10 CAT_DURATION_SECONDS=8 npm start
```

启动时加 `--cat-now` 参数，会马上召唤一次猫猫。

### 每只猫的配置

- `src/cats.json`：每只猫的版本号、程序名、appId、托盘显示的名字，以及猫在屏幕上的位置（`right` 靠右下角，`center` 底部居中）。
- `assets/cats/<猫>/`：`cat.webm`（带透明通道的视频）、`icon.ico`、`icon.png`、`tray.png`、`tray@2x.png`。

不同的猫 appId 不一样，所以可以同时安装、同时运行，设置也各存各的。

### 打包

每次推送到 `main`（改动了 `src/`、`assets/`、`package.json` 或 `electron-builder.config.js`），GitHub Actions 会在 Windows 环境里给每只猫各打一次包，发布到 Releases：

- 暹罗猫的 tag 是 `v<版本号>`，曼基康的是 `munchkin-v<版本号>`，版本号取 `src/cats.json`。
- **同一个 tag 已经发布过的话，那只猫会直接跳过，不会覆盖。** 想给某只猫发新版，就把它在 `src/cats.json` 里的版本号改大。

本地打包某一只：

```bash
CAT_VARIANT=munchkin npm run dist
```

### 换一只猫

`tools/make_cat_video.py` 可以把一段猫视频处理成带透明通道的 VP9 视频：用 BiRefNet 逐帧抠图，修掉边缘的杂色，最后正放加倒放拼成一段无缝循环。

```bash
python -m venv venv
venv/bin/pip install "rembg[cpu]" scipy pillow numpy
venv/bin/python tools/make_cat_video.py 你的猫.mp4 assets/cats/<猫>/cat.webm --work work
```

需要先装好 ffmpeg。在 CPU 上每帧大约要 20 多秒。

暹罗猫用的参数：把前面的篮子按帧沿横杆切掉，再把画面往下挪，让猫从屏幕底部升上来。

```bash
venv/bin/python tools/make_cat_video.py cat.mp4 assets/cats/siamese/cat.webm --work work --no-fill \
  --cut-keys "1:790,12:784,24:804,36:804,42:864,46:904,50:960,54:1000,58:1050,62:1100" \
  --cut-slope -0.036 --lift-keys "1:1080,18:1080,31:0"
```

曼基康用的参数：原视频是手机竖拍的，先截取 21.4–26.2 秒、按 30fps 导出帧，再以猫身体底部为锚点做防抖，把猫放大到撑满画面高度，底部沿毯子的边缘渐隐。

```bash
mkdir -p work/frames
ffmpeg -ss 21.4 -to 26.2 -i munchkin.mp4 -vf fps=30 -an work/frames/%04d.png
venv/bin/python tools/make_cat_video.py munchkin.mp4 assets/cats/munchkin/cat.webm --work work \
  --skip-extract --no-fill --frame 1440x1080 --fps 30
```
