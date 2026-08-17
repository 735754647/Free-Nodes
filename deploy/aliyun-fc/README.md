# 阿里云函数 TCP 复核

此目录的 `index.py` 是 GitHub Actions 可选阿里云复核使用的函数代码。

在阿里云 Function Compute 创建 Python 运行时 HTTP 函数后，上传 `index.py`，并将处理程序设为：

```text
index.handler
```

函数不依赖第三方 Python 包。它只检查目标入口的 TCP 端口能否连接，并返回 `ok` 或 `fail`；协议真实性、Google 204 延迟和可选下载测速仍由 GitHub Actions 中的 Mihomo 完成。

将函数 HTTP 触发器地址保存到仓库的 `ALIYUN_FC_URL` Secret，例如：

```text
http://your-function.cn-hangzhou.fcapp.run/
```

请保持地址不带引号；末尾的 `/` 可有可无。
