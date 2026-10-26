"""Build TierLense's ordered Groq -> OpenRouter -> Mistral provider chains."""
from tierlense.core.config import Settings
from tierlense.intelligence.groq_provider import GroqBrowserSearchProvider, GroqIntelligenceProvider
from tierlense.intelligence.provider_adapters import (
    MistralBrowserSearchProvider, MistralIntelligenceProvider,
    OpenRouterBrowserSearchProvider, OpenRouterIntelligenceProvider,
)
from tierlense.intelligence.provider_failover import (
    FailoverIntelligenceProvider, FailoverSourceDiscoveryProvider, ProviderCooldownRegistry,
)


def build_provider_chains(settings: Settings):
    """Create providers in configured priority order, sharing quota cooldowns."""
    cooldowns = ProviderCooldownRegistry()
    discovery = []
    intelligence = []
    if settings.get_groq_api_key():
        discovery.append(GroqBrowserSearchProvider(settings))
        intelligence.append(GroqIntelligenceProvider(settings))
    if settings.get_openrouter_api_key():
        discovery.append(OpenRouterBrowserSearchProvider(settings))
        intelligence.append(OpenRouterIntelligenceProvider(settings))
    if settings.get_mistral_api_key():
        discovery.append(MistralBrowserSearchProvider(settings))
        intelligence.append(MistralIntelligenceProvider(settings))
    return (
        FailoverSourceDiscoveryProvider(discovery, cooldowns=cooldowns,
            failure_cooldown_seconds=settings.provider_failure_cooldown_seconds, chain_name="source discovery"),
        FailoverIntelligenceProvider(intelligence, cooldowns=cooldowns,
            failure_cooldown_seconds=settings.provider_failure_cooldown_seconds, chain_name="model inference"),
    )
