# AI-DLC: Units Generation
*Source: [awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows) — `aidlc-rules/aws-aidlc-rule-details/inception/units-generation.md`*

---

## Definition

A **Unit of Work** is a logical grouping of stories for development purposes.
- For microservices: each unit becomes an independently deployable service.
- For monoliths: the single unit represents the entire application with logical modules.

**Terminology:**
- "Service" — independently deployable components
- "Module" — logical groupings within a service
- "Unit of Work" — planning context

---

## Prerequisites

- Workspace Detection complete
- Requirements Analysis recommended
- User Stories recommended (stories map to units)
- **Application Design stage REQUIRED** (determines components, methods, and services)

---

## Part 1: Planning

**Step 1** — Create unit decomposition plan with checkboxes.

**Step 2** — Include mandatory artifacts:
- `aidlc-docs/inception/application-design/unit-of-work.md` — unit definitions and responsibilities
- `aidlc-docs/inception/application-design/unit-of-work-dependency.md` — dependency matrix
- `aidlc-docs/inception/application-design/unit-of-work-story-map.md` — stories mapped to units

**Step 3** — Generate context-appropriate questions across:
- **Story Grouping** — grouping strategy, story affinity, logical clustering
- **Dependencies** — integration approach, shared resources, inter-unit communication
- **Team Alignment** — team structure, ownership boundaries
- **Technical Considerations** — scalability/deployment requirements per unit
- **Business Domain** — domain boundaries, bounded contexts, business capability alignment
- **Code Organization** (green field, multi-unit only)

**Steps 4–11** — Store plan → collect answers → analyze for ambiguities → follow-up questions → get explicit approval → log approval.

---

## Part 2: Generation

**Steps 12–19** — Load approved plan → execute each step → generate unit artifacts → present completion → await explicit approval.

**Completion criteria:**
- All planning questions answered and ambiguities resolved
- Explicit user approval obtained
- All steps in unit-of-work plan marked complete
- `unit-of-work.md`, `unit-of-work-dependency.md`, `unit-of-work-story-map.md` generated
- Units verified and ready for per-unit design stages

---

## Hello Scrum Mapping

In hello-scrum, Units Generation is part of the Elaborate step. The single `unit` object contains:
- `name` — unit name (e.g., "Sprint Leaderboard")
- `domain` — domain label (e.g., "Sprint Performance")
- `stories[]` — array of user stories with AC
- `bolts[]` — suggested sprint groupings (Bolts reference story indices)
- `nfrs[]` — non-functional requirements
- `risks[]` — identified risks

Hello-scrum currently generates one Unit per Inception run. Multi-unit support is deferred until multi-agent is ready.
