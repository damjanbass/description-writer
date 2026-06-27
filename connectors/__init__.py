"""Platform connectors. Phase 1 ships WooCommerce (REST API, lowest effort,
most common). Magento is Phase 1-second; domestic platforms (Selltico, TAU
Commerce) are the Phase 2 distribution moat. Every connector implements the
`connectors.base.Connector` contract so the pipeline runner is connector-
agnostic.
"""
