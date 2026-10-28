# 暹罗猫休息提醒 SiameseBreak

每工作 30 分钟，就会有一只真的暹罗猫从屏幕底下钻出来，占满屏幕卖萌 1 分钟，提醒你起来活动一下。

## 同事怎么用

1. 打开 [Releases](https://github.com/WHXisWH/siamese-break/releases/latest)，下载 `SiameseBreak-Setup-x.x.x.exe`。
2. 双击安装。安装不需要管理员权限，装完会自动运行。
   - 如果 Windows 弹出“Windows 已保护你的电脑”，点 **更多信息** → **仍要运行**。这是因为程序没有购买代码签名证书，不是病毒。
3. 程序会常驻在屏幕右下角的托盘区（猫头图标，可能要先点 `^` 展开才能看到），默认开机自动启动。

不想安装的话，也可以下载 `SiameseBreak-Portable-x.x.x.exe`，双击直接运行。

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
```

调试时可以用环境变量缩短时间：

```bash
SIAMESE_INTERVAL_SECONDS=10 SIAMESE_DURATION_SECONDS=8 npm start
```

启动时加 `--cat-now` 参数，会马上召唤一次猫猫。

### 打包

每次推送到 `main`（改动了 `src/`、`assets/` 或 `package.json`），GitHub Actions 都会在 Windows 环境里打包，并把安装包发布到 Releases，版本号取 `package.json` 里的 `version`。发新版时记得先改版本号；版本号不变的话，会覆盖同版本的安装包。也可以在 Actions 页面手动运行 `build`。

### 换一只猫

`assets/cat.webm` 是带透明通道的 VP9 视频。`tools/make_cat_video.py` 可以把任意一段猫视频处理成这个格式：用 BiRefNet 逐帧抠图，修掉边缘的杂色，把猫前面的遮挡物（比如篮子）补回来，最后正放加倒放拼成一段无缝循环。

```bash
python -m venv venv
venv/bin/pip install "rembg[cpu]" scipy pillow numpy
venv/bin/python tools/make_cat_video.py 你的猫.mp4 assets/cat.webm --work work
```

需要先装好 ffmpeg。在 CPU 上每帧大约要 20 多秒。

现在这只猫是用下面的参数做的：前面的篮子按帧沿横杆切掉，再把画面往下挪，让猫从屏幕底部升上来。

```bash
venv/bin/python tools/make_cat_video.py cat.mp4 assets/cat.webm --work work --no-fill \
  --cut-keys "1:790,12:784,24:804,36:804,42:864,46:904,50:960,54:1000,58:1050,62:1100" \
  --cut-slope -0.036 --lift-keys "1:1080,18:1080,31:0"
```
