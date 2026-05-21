"""
Example: Colectica → Purview Sync Agent

Demonstrates how to use the Colectica-Purview sync agent.

Run: python integrations/examples/orchestration_example.py
"""

from integrations.agents import Colectica_PurviewAgent


def main():
    """Run example sync workflow."""
    agent = Colectica_PurviewAgent()

    print("\n" + "=" * 70)
    print("Colectica → Purview Sync Agent")
    print("=" * 70)

    # Example 1: Preview sync (dry run)
    print("\n[Example 1] Preview sync without mutations...")
    agent.sync_survey_items(
        query="type:QuestionItem",
        dry_run=True,
        limit=50,
    )

    # Example 2: Actual sync (would create/update in Purview)
    print("\n[Example 2] Actual sync (requires real MCP servers)...")
    # agent.sync_survey_items(query="type:QuestionItem", dry_run=False, limit=50)

    # Example 3: Validate consistency
    print("\n[Example 3] Validate consistency between systems...")
    agent.validate_consistency()


if __name__ == "__main__":
    main()
