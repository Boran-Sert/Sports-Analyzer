"""
Sports-Analyzer Core: Similarity Engine (Showcase Version)

This module contains the pattern matching logic used to identify historical 
matches with similar odds profiles. 

NOTE: The proprietary advanced weighting algorithms have been abstracted 
in this showcase version.
"""

import math
from pydantic import BaseModel
from core.config import TierLimits
from repositories.match_repository import MatchRepository
from schemas.auth import UserTier
from schemas.match import MatchInDB
from utils.cache import cache_response

class SimilarMatchResult(BaseModel):
    """Result object for the similarity engine."""
    match: MatchInDB
    distance: float
    similarity_percentage: float

class AnalysisService:
    """Matches upcoming events against historical data points."""

    def __init__(self, match_repo: MatchRepository):
        self.repo = match_repo

    @cache_response(ttl_seconds=3600, prefix="analysis:similar")
    async def find_similar_matches(
        self,
        target_match_id: str,
        user_tier: UserTier,
        is_superuser: bool = False,
        limit_override: int | None = None
    ) -> list[SimilarMatchResult]:
        """
        Finds historical matches most similar to a target upcoming match.
        
        This implementation uses a standard Euclidean distance model on 1X2 odds.
        In the production version, this is supplemented with league-specific 
        weighting and market-specific adjustments.
        """
        # 1. Locate target event
        target = await self.repo.get_by_external_id(target_match_id)
        if not target or target.status.value != "upcoming":
            return []

        if not target.odds or not getattr(target.odds, "h2h", None):
            return []
            
        target_odds = target.odds.h2h
        if target_odds.home is None or target_odds.draw is None or target_odds.away is None:
            return []

        # 2. Determine Tier Limits
        tier_limit = TierLimits.get_similar_limit(user_tier.value)
        final_limit = tier_limit
        if is_superuser:
            final_limit = limit_override or 50
        elif (user_tier in [UserTier.PRO, UserTier.ELITE]) and limit_override:
            final_limit = min(limit_override, tier_limit)

        # 3. Fetch Historical Data (Sampled for Showcase Performance)
        historical_matches = await self.repo.get_completed_matches_for_analysis(limit=2000)

        # 4. Pattern Matching Calculation (Abstracted)
        results: list[SimilarMatchResult] = []
        for match in historical_matches:
            if not getattr(match, "odds", None) or not getattr(match.odds, "h2h", None):
                continue
                
            hist_odds = match.odds.h2h
            if hist_odds.home is None or hist_odds.draw is None or hist_odds.away is None:
                continue

            # Standard Euclidean Distance Implementation
            # d = sqrt((x2 - x1)^2 + (y2 - y1)^2 + (z2 - z1)^2)
            distance = math.sqrt(
                (target_odds.home - hist_odds.home) ** 2 +
                (target_odds.draw - hist_odds.draw) ** 2 +
                (target_odds.away - hist_odds.away) ** 2
            )

            # Filtering and Scoring
            if distance < 3.0:
                # Normalizing distance to a percentage (0 to 100)
                sim_pct = max(0.0, 100.0 - (distance * 33.3))
                
                results.append(SimilarMatchResult(
                    match=match,
                    distance=round(distance, 4),
                    similarity_percentage=round(sim_pct, 1)
                ))

        # 5. Sort by proximity
        results.sort(key=lambda x: x.distance)

        # 6. Uniqueness Filter (Ensuring high-quality match variety)
        seen_matches = set()
        unique_results = []
        for res in results:
            match_key = (
                res.match.commence_time.date(),
                res.match.home_team,
                res.match.away_team
            )
            if match_key not in seen_matches:
                seen_matches.add(match_key)
                unique_results.append(res)
            
            if len(unique_results) >= final_limit:
                break

        return unique_results
