"""企业微信通知模块：将选股结果通过 Webhook 推送至企业微信群。"""

import json
from datetime import date

import requests

from sequoia_x.core.config import Settings
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)


class FeishuNotifier:
    """企业微信 Webhook 推送器（原飞书类名保留，以兼容调用方）。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _to_xueqiu_code(code: str) -> str:
        """将纯数字代码转为雪球格式：6开头→SH，4/8开头→BJ，其余→SZ。"""
        if code.startswith("6"):
            return f"SH{code}"
        elif code.startswith(("4", "8")):
            return f"BJ{code}"
        return f"SZ{code}"

    @staticmethod
    def _get_stock_names(symbols: list[str]) -> dict[str, str]:
        """通过 baostock 批量查询股票名称，返回 {code: name} 映射。"""
        import baostock as bs
        bs.login()
        mapping = {}
        for code in symbols:
            prefix = "sh" if code.startswith(("6", "9")) else "sz"
            rs = bs.query_stock_basic(code=f"{prefix}.{code}")
            while rs.next():
                row = rs.get_row_data()
                mapping[code] = row[1]  # 第2个字段是股票名称
        bs.logout()
        return mapping

    def _build_markdown(self, symbols: list[str], strategy_name: str) -> str:
        """构建企业微信支持的 Markdown 文本（长度控制在 4096 字节内）。"""
        today = date.today().strftime("%Y-%m-%d")
        names = self._get_stock_names(symbols)

        # 生成股票列表，每行一个 [名称](雪球链接)
        lines = []
        for code in symbols:
            xq_code = self._to_xueqiu_code(code)
            name = names.get(code, code)
            lines.append(f"- [{name}](https://xueqiu.com/S/{xq_code})")

        # 如果股票太多（超过 50 只），只显示前 50 只并提示
        if len(lines) > 50:
            lines = lines[:50]
            lines.append(f"\n> ... 共 {len(symbols)} 只，仅显示前 50 只")

        stock_text = "\n".join(lines) if lines else "（无选股结果）"

        # 企业微信 markdown 标题用 #，加粗用 **
        content = (
            f"# 📈 Sequoia-X 选股播报 | {strategy_name}\n\n"
            f"**日期：** {today}\n"
            f"**策略：** {strategy_name}\n"
            f"**选股数量：** {len(symbols)}\n\n"
            f"**选股列表：**\n{stock_text}"
        )

        # 截断到 4000 字符，防止超限（企业微信 markdown 限制 4096 字节）
        if len(content) > 4000:
            content = content[:3997] + "..."
        return content

    def send(
        self,
        symbols: list[str],
        strategy_name: str,
        webhook_key: str = "default",
    ) -> None:
        """
        将选股结果格式化为企业微信 Markdown 消息并 POST 至 Webhook。

        Args:
            symbols: 选股结果代码列表。
            strategy_name: 策略名称，用于消息标题。
            webhook_key: 策略标识（保留参数，本实现未使用，但保留兼容性）。
        """
        # 从 settings 中读取企业微信 Webhook URL（需在 .env 中定义）
        url = getattr(self.settings, "wechat_webhook_url", None)
        if not url:
            logger.error("未配置企业微信 Webhook URL，请在 .env 中设置 WECHAT_WEBHOOK_URL")
            return

        content = self._build_markdown(symbols, strategy_name)
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }

        try:
            resp = requests.post(
                url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            # 企业微信返回格式：{"errcode":0,"errmsg":"ok"}
            resp_json = resp.json()
            if resp.status_code == 200 and resp_json.get("errcode") == 0:
                logger.info(f"企业微信推送成功，共 {len(symbols)} 只股票")
            else:
                logger.error(
                    f"企业微信推送失败，HTTP状态={resp.status_code}，"
                    f"响应={resp.text}"
                )
        except requests.RequestException as exc:
            logger.error(f"企业微信推送请求异常：{exc}")
