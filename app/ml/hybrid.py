"""
Phase 3 — Hybrid detection: deterministic rules + ML anomaly score.

Initial approach: ML model alone (Isolation Forest).
Problem: Missed obvious brute-force attacks with very predictable patterns.
Solution: Add deterministic rule layer that fires on specific behaviors:
  - Brute force: 10+ failed auths in 60s on same IP
  - DDoS: 40+ requests/sec from single source
  - Scanner: Known exploit paths

This hybrid approach avoids false negatives on known attacks while 
letting ML catch novel patterns the rules don't cover.

Combined score = weighted sum (rule_weight=0.4, ml_weight=0.6)
You can tune these weights based on your false positive tolerance.
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("soc.ml.hybrid")


# rule thresholds
BRUTE_FORCE_FAIL_THRESHOLD = 10  # failed auths in 1min from same IP
DDOS_BURST_THRESHOLD = 40.0      # requests per second (burst rate feature)
SUSPICIOUS_PATH_KEYWORDS = [
    "admin", "shell", "passwd", "phpmyadmin", "cgi-bin",
    "..%2f", "../", ".env", "wp-admin", "debug",
]


def apply_rules(features: np.ndarray, event: dict) -> tuple[float, Optional[str]]:
    """
    Evaluate deterministic rules against the feature vector and raw event.
    Returns (rule_score, attack_type) where rule_score is 0 or 1.
    """
    path = event.get("path", "").lower()
    status = event.get("status_code") or 0

    # feature indices (must match FeatureEngine.FEATURE_NAMES order)
    ip_fail_1m = features[2]
    burst_rate = features[11]
    is_auth = features[7]

    # brute force: lots of 401s on auth endpoints in a short window
    if ip_fail_1m >= BRUTE_FORCE_FAIL_THRESHOLD and is_auth > 0:
        logger.debug("rule hit: brute_force (fails=%d)", ip_fail_1m)
        return 1.0, "brute_force"

    # DDoS spike: absurd burst rate from a single source
    if burst_rate >= DDOS_BURST_THRESHOLD:
        logger.debug("rule hit: ddos_spike (burst=%.1f)", burst_rate)
        return 1.0, "ddos_spike"

    # suspicious path: common scanner / exploit paths
    for keyword in SUSPICIOUS_PATH_KEYWORDS:
        if keyword in path:
            logger.debug("rule hit: suspicious_api (path=%s)", path)
            return 0.8, "suspicious_api"

    # no rule fired
    return 0.0, None


def hybrid_score(
    ml_score: float,
    features: np.ndarray,
    event: dict,
    ml_weight: float = 0.6,
    rule_weight: float = 0.4,
) -> tuple[float, Optional[str]]:
    """
    Combine ML anomaly score with rule-based detection.
    Returns (combined_score, attack_type).

    Weights are configurable; defaults favor ML slightly since rules
    only catch known patterns while ML generalizes.
    """
    rule_score, attack_type = apply_rules(features, event)

    # if a rule fires, boost the combined score so it's always above threshold
    if rule_score > 0:
        combined = max(
            ml_weight * ml_score + rule_weight * rule_score,
            rule_score * 0.9,  # floor: rule alone should almost always alert
        )
    else:
        combined = ml_score  # pure ML signal
        # infer attack type from ML score if high enough
        if combined > 0.7:
            attack_type = "anomaly"

    return min(combined, 1.0), attack_type
