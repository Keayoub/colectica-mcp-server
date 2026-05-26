const capabilities = [
  {
    title: "Operation discovery",
    text: "Expose OpenAPI operations with health checks, categories, details, and keyword search so agents can discover the surface safely.",
    accent: "Start with health_check and list_operation_categories.",
  },
  {
    title: "Metadata retrieval",
    text: "Fetch items, item sets, descriptions, versions, DDI fragments, and JSON fragments for survey metadata reasoning and enrichment.",
    accent: "Designed for questions, variables, concepts, universes, and code lists.",
  },
  {
    title: "Controlled mutation",
    text: "Register items, update state, tag, comment, rate, and use transactions for atomic repository changes with explicit audit boundaries.",
    accent: "Prefer reversible, minimal updates.",
  },
  {
    title: "Relationship analysis",
    text: "Search subject and object relationships, inspect relationship matrices, and reason across study structures and linked metadata.",
    accent: "Useful for harmonization and cross-survey analysis.",
  },
  {
    title: "Pagination and retries",
    text: "Aggregate large result sets with continuation handling while keeping retry policy and OpenAPI caching inside the server layer.",
    accent: "Works well for query-heavy repositories.",
  },
  {
    title: "Agent integration",
    text: "Support desktop and hosted agent runtimes with a single MCP tool contract and focused docs for Foundry, LangChain, LlamaIndex, and custom clients.",
    accent: "Framework-agnostic by design.",
  },
];

const toolFamilies = [
  {
    title: "Discovery",
    text: "health_check, list_operations, find_operations, operation_details, and category-based browsing.",
  },
  {
    title: "Items and search",
    text: "get_item, search, get_item_by_urn, versions, summaries, descriptions, and latest-version helpers.",
  },
  {
    title: "DDI and JSON",
    text: "get_ddi_fragment, get_ddi_set_fragment, get_item_json, and filtered item-set traversal.",
  },
  {
    title: "Relationships and sets",
    text: "Relationship search, typed matrices, item sets, and versioned set retrieval for deep metadata graphs.",
  },
];

const integrations = [
  {
    title: "Framework-agnostic guide",
    meta: "Architecture and platform selection",
    text: "Use the comparison guide when you need to choose between local orchestration, managed Azure flows, or custom implementations.",
    href: "https://github.com/Keayoub/colectica-mcp-server/blob/main/integrations/docs/FRAMEWORK_AGNOSTIC.md",
  },
  {
    title: "AI Foundry statistician agent",
    meta: "Survey metadata workflows",
    text: "Focuses on discovery, harmonization, quality, DDI retrieval, and safe registration patterns for statistical program teams.",
    href: "https://github.com/Keayoub/colectica-mcp-server/blob/main/integrations/aifoundry/statistician_prompt_agent.py",
  },
  {
    title: "Custom agent definition",
    meta: "Low-level orchestration",
    text: "Map MCP tools into your own runtime when you want precise control over prompt, execution, and lifecycle management.",
    href: "https://github.com/Keayoub/colectica-mcp-server/blob/main/integrations/docs/AGENT_CUSTOM.md",
  },
  {
    title: "LangChain and LlamaIndex",
    meta: "Composable orchestration",
    text: "Add Colectica tools to larger RAG, workflow, or multi-agent systems without changing the server contract.",
    href: "https://github.com/Keayoub/colectica-mcp-server/tree/main/integrations/docs",
  },
  {
    title: "Azure hosting",
    meta: "Functions and Bicep",
    text: "Use the hosting and infra folders when you need a remote streamable HTTP endpoint running in Azure.",
    href: "https://github.com/Keayoub/colectica-mcp-server/tree/main/hosting",
  },
  {
    title: "Examples",
    meta: "Working reference code",
    text: "Smoke checks and orchestration examples show how to wire the MCP server into local and cloud execution paths.",
    href: "https://github.com/Keayoub/colectica-mcp-server/tree/main/integrations/examples",
  },
];

const releases = [
  "v0.3.2",
  "v0.3.1",
  "v0.3.0",
  "v0.2.2",
  "v0.2.1",
  "v0.2.0",
];

function renderCards(targetId, items, renderItem) {
  const target = document.getElementById(targetId);
  if (!target) {
    return;
  }
  target.innerHTML = items.map(renderItem).join("");
}

renderCards(
  "capability-grid",
  capabilities,
  (item) => `
    <article class="card">
      <strong>${item.title}</strong>
      <p>${item.text}</p>
      <em>${item.accent}</em>
    </article>
  `,
);

renderCards(
  "tool-grid",
  toolFamilies,
  (item) => `
    <article class="card">
      <strong>${item.title}</strong>
      <p>${item.text}</p>
    </article>
  `,
);

renderCards(
  "integration-grid",
  integrations,
  (item) => `
    <article class="card">
      <span class="integration-meta">${item.meta}</span>
      <strong>${item.title}</strong>
      <p>${item.text}</p>
      <a class="integration-link" href="${item.href}" target="_blank" rel="noreferrer">Open guide</a>
    </article>
  `,
);

renderCards(
  "release-grid",
  releases,
  (version) => `
    <article class="timeline-item">
      <span>${version}</span>
      <strong>Release summary</strong>
      <p>Review the markdown notes for changes, additions, and migration details for ${version}.</p>
      <a class="integration-link" href="https://github.com/Keayoub/colectica-mcp-server/blob/main/releases/${version}.md" target="_blank" rel="noreferrer">Read notes</a>
    </article>
  `,
);