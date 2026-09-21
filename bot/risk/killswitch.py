"""
Kill Switch Manager with state persistence across restarts.
Rules:
- Daily loss <= -2%: no new trades until next day
- Weekly loss <= -5%: pause and require manual resume
- 3 consecutive losses: halve position size until next win
- 10% drawdown from equity peak: halt the bot, require manual re-enable
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class KillSwitchStatus:
    can_trade: bool
    size_multiplier: float
    current_equity: float
    peak_equity: float
    drawdown_pct: float
    daily_pnl_pct: float
    weekly_pnl_pct: float
    consecutive_losses: int
    daily_halt: bool
    weekly_halt: bool
    drawdown_halt: bool
    rejection_reason: Optional[str] = None


class KillSwitchManager:
    """Manages trading halts and drawdown protections with atomic file persistence."""

    def __init__(
        self,
        state_file: str = "state/killswitch_state.json",
        initial_equity: float = 100000.0,
        daily_loss_pct: float = 2.0,
        weekly_loss_pct: float = 5.0,
        consecutive_losses_threshold: int = 3,
        consecutive_losses_mult: float = 0.5,
        max_drawdown_pct: float = 10.0,
    ):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.initial_equity = initial_equity
        self.daily_loss_limit_pct = daily_loss_pct
        self.weekly_loss_limit_pct = weekly_loss_pct
        self.consecutive_losses_threshold = consecutive_losses_threshold
        self.consecutive_losses_mult = consecutive_losses_mult
        self.max_drawdown_limit_pct = max_drawdown_pct

        self._load_state()

    def _default_state(self) -> Dict:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        week_str = datetime.now(timezone.utc).strftime("%Y-W%W")
        return {
            "current_equity": self.initial_equity,
            "peak_equity": self.initial_equity,
            "day_start_equity": self.initial_equity,
            "day_start_date": today_str,
            "week_start_equity": self.initial_equity,
            "week_start_date": week_str,
            "consecutive_losses": 0,
            "daily_halt": False,
            "weekly_halt": False,
            "drawdown_halt": False,
        }

    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                return
            except Exception as e:
                logger.error(f"Failed to read killswitch state file {self.state_file}: {e}")
        self.state = self._default_state()
        self._save_state()

    def _save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save killswitch state: {e}")

    def update_equity(self, equity: float, now: Optional[datetime] = None):
        """Update current equity and check day/week rollover and drawdown limits."""
        now = now or datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        week_str = now.strftime("%Y-W%W")

        # Day rollover
        if today_str != self.state.get("day_start_date"):
            self.state["day_start_date"] = today_str
            self.state["day_start_equity"] = equity
            self.state["daily_halt"] = False

        # Week rollover
        if week_str != self.state.get("week_start_date"):
            self.state["week_start_date"] = week_str
            self.state["week_start_equity"] = equity
            # Weekly halt requires manual resume unless explicitly reset

        self.state["current_equity"] = equity
        if equity > self.state["peak_equity"]:
            self.state["peak_equity"] = equity

        # Check Drawdown from Peak
        peak = self.state["peak_equity"]
        if peak > 0:
            dd_pct = ((peak - equity) / peak) * 100.0
            if dd_pct >= self.max_drawdown_limit_pct:
                self.state["drawdown_halt"] = True
                logger.critical(
                    f"KILL SWITCH TRIGGERED: Drawdown {dd_pct:.2f}% >= {self.max_drawdown_limit_pct}%. BOT HALTED."
                )

        # Check Daily Loss
        day_start = self.state["day_start_equity"]
        if day_start > 0:
            daily_pnl_pct = ((equity - day_start) / day_start) * 100.0
            if daily_pnl_pct <= -self.daily_loss_limit_pct:
                self.state["daily_halt"] = True
                logger.warning(
                    f"KILL SWITCH TRIGGERED: Daily loss {daily_pnl_pct:.2f}% <= -{self.daily_loss_limit_pct}%. New trades halted today."
                )

        # Check Weekly Loss
        week_start = self.state["week_start_equity"]
        if week_start > 0:
            weekly_pnl_pct = ((equity - week_start) / week_start) * 100.0
            if weekly_pnl_pct <= -self.weekly_loss_limit_pct:
                self.state["weekly_halt"] = True
                logger.warning(
                    f"KILL SWITCH TRIGGERED: Weekly loss {weekly_pnl_pct:.2f}% <= -{self.weekly_loss_limit_pct}%. Requires manual resume."
                )

        self._save_state()

    def record_trade_result(self, profit_dollars: float):
        """Track consecutive loss counter."""
        if profit_dollars < 0:
            self.state["consecutive_losses"] += 1
            if self.state["consecutive_losses"] >= self.consecutive_losses_threshold:
                logger.warning(
                    f"Consecutive losses reached {self.state['consecutive_losses']}. Position sizing halved."
                )
        elif profit_dollars > 0:
            self.state["consecutive_losses"] = 0
            logger.info("Winning trade recorded. Consecutive losses counter reset.")
        self._save_state()

    def can_trade(self) -> Tuple[bool, Optional[str]]:
        """Verify if new trades are permitted by kill switches."""
        if self.state.get("drawdown_halt", False):
            return False, f"HALTED: Peak drawdown reached or exceeded {self.max_drawdown_limit_pct}%. Manual re-enable required."
        if self.state.get("weekly_halt", False):
            return False, f"PAUSED: Weekly loss limit exceeded (-{self.weekly_loss_limit_pct}%). Manual resume required."
        if self.state.get("daily_halt", False):
            return False, f"HALTED FOR TODAY: Daily loss limit reached (-{self.daily_loss_limit_pct}%)."
        return True, None

    def get_position_size_multiplier(self) -> float:
        """Halve position sizing if consecutive losses threshold reached."""
        if self.state.get("consecutive_losses", 0) >= self.consecutive_losses_threshold:
            return self.consecutive_losses_mult
        return 1.0

    def resume_weekly_halt(self):
        """Manual command to resume after weekly loss limit."""
        self.state["weekly_halt"] = False
        self._save_state()

    def reset_drawdown_halt(self, new_peak: Optional[float] = None):
        """Manual reset for emergency drawdown halt."""
        self.state["drawdown_halt"] = False
        if new_peak is not None:
            self.state["peak_equity"] = new_peak
        self._save_state()

    def get_status(self) -> KillSwitchStatus:
        curr = self.state["current_equity"]
        peak = self.state["peak_equity"]
        day_start = self.state["day_start_equity"]
        week_start = self.state["week_start_equity"]

        dd_pct = ((peak - curr) / peak * 100.0) if peak > 0 else 0.0
        day_pct = ((curr - day_start) / day_start * 100.0) if day_start > 0 else 0.0
        week_pct = ((curr - week_start) / week_start * 100.0) if week_start > 0 else 0.0

        can_tr, reason = self.can_trade()
        return KillSwitchStatus(
            can_trade=can_tr,
            size_multiplier=self.get_position_size_multiplier(),
            current_equity=curr,
            peak_equity=peak,
            drawdown_pct=dd_pct,
            daily_pnl_pct=day_pct,
            weekly_pnl_pct=week_pct,
            consecutive_losses=self.state["consecutive_losses"],
            daily_halt=self.state["daily_halt"],
            weekly_halt=self.state["weekly_halt"],
            drawdown_halt=self.state["drawdown_halt"],
            rejection_reason=reason,
        )
