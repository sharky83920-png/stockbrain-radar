"""StockBrain Radar 套件初始化。

在這裡注入 truststore，讓 Python 改用「Windows 系統憑證庫」做 TLS 驗證。
原因：本機 Norton 防毒開了 SSL/TLS 掃描，會 MITM 攔截 HTTPS 並用自己的
「Norton Web/Mail Shield Root」憑證重簽。該根憑證在 Windows 系統憑證庫裡（Norton 裝的），
但不在 Python 的 certifi 憑證庫裡，導致 requests 連 FinMind/Google 等全部 SSL 驗證失敗。
truststore 讓我們沿用系統信任鏈即可（不必關閉驗證、不犧牲安全性）。
import src 越早越好——任何 HTTPS 連線發生前就會生效。
"""
try:
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # truststore 沒裝或注入失敗時，不擋程式啟動（仍可能 SSL 失敗）
    pass
