# AI-Driven Development Lifecycle (AI-DLC)
**Raja SP, Amazon Web Services**

---

## I. Context

The evolution of software engineering has been a continuous quest to enable developers to focus on solving complex problems by abstracting away lower-level, undifferentiated tasks. From early machine code to high-level programming languages and the adoption of APIs and libraries, each step has significantly boosted developer productivity.

Now, the integration of Large Language Models has revolutionized how software is created, introducing conversational natural language interactions for tasks like code generation, bug detection, and test generation. This marks the **AI-Assisted era**, where AI enhances fine-grained, specific tasks.

As AI evolves, its applications are expanding beyond code generation to include requirements elaboration, planning, task decomposition, design, and real-time collaboration with developers. This shift is kick-starting the **AI-Driven era**, where AI actively orchestrates the development process.

This paper introduces the **AI-Driven Development Lifecycle (AI-DLC)**, a reimagined, AI-native methodology designed to fully integrate the capabilities of AI.

---

## II. Key Principles

1. **Reimagine Rather Than Retrofit** — Traditional methods were built for months-long iterations. AI enables cycles measured in hours or days.
2. **Reverse the Conversation Direction** — AI initiates and directs conversations; humans serve as approvers at critical junctures.
3. **Integration of Design Techniques into the Core** — DDD, BDD, or TDD are integral to AI-DLC, not optional add-ons.
4. **Align with AI Capability** — AI-Driven paradigm balances human oversight with current AI capabilities and limitations.
5. **Cater to Building Complex Systems** — Designed for systems requiring architectural complexity, scalability, and multi-team coordination.
6. **Retain What Enhances Human Symbiosis** — User stories, risk registers, and other human-validation touchpoints are retained.
7. **Facilitate Transition Through Familiarity** — Sprints → **Bolts** (same concept, hours/days not weeks).
8. **Streamline Responsibilities for Efficiency** — AI enables developers to transcend specialization silos.
9. **Minimise Stages, Maximise Flow** — Minimal phases specifically designed for human oversight at critical junctures.
10. **No Hard-Wired, Opinionated SDLC Workflows** — AI recommends plans; humans verify and moderate.

---

## III. Core Framework

### Artifacts

**Intent** — A high-level statement of purpose. Starting point for AI-driven decomposition.
> Example: "Develop a recommendation engine for cross-selling products."

**Unit** — A cohesive, self-contained work element derived from an Intent. Analogous to **Epics in Scrum** / Subdomains in DDD. Each Unit encompasses a set of user stories. Loosely coupled, independently deployable.

**Bolt** — The smallest iteration in AI-DLC. Analogous to a **Sprint**. Build-validation cycles measured in hours or days. Each Bolt encapsulates a well-defined scope (a collection of user stories within a Unit). A Unit can be executed through one or more Bolts, running in parallel or sequentially.

**Domain Design** — Models the core business logic of a Unit using DDD principles (aggregates, value objects, entities, domain events, repositories, factories).

**Logical Design** — Translates Domain Design for NFRs using architectural patterns (CQRS, Circuit Breakers, etc.). AI creates Architecture Decision Records (ADRs).

**Deployment Units** — Packaged executable code (container images, serverless functions), configurations (Helm Charts), and infrastructure components (Terraform/CFN stacks), rigorously tested for functional acceptance, security, and NFRs.

---

### Phases & Rituals

#### Inception Phase — Mob Elaboration

Collaborative requirements elaboration in a single room with a shared screen.

**Steps:**
a. AI asks clarifying questions — ensures comprehensive understanding of the goal  
b. AI elaborates into user stories, NFRs, and risk descriptions — team validates  
c. AI composes stories into Units (e.g., "User Data Collection," "Recommendation Algorithm")  
d. Product Owner validates and refines Units  
e. AI generates a PRFAQ (optional)  
f. Developers and PO validate PRFAQ and risks  

**Outputs:** PRFAQ · User Stories + AC · NFR definitions · Risk descriptions · Measurement Criteria · Suggested Bolts

#### Construction Phase — Mob Construction/Programming

Transforms Units into tested, operations-ready Deployment Units.

a. Domain Design — AI models business logic using DDD  
b. Logical Design — AI applies NFRs and architectural patterns  
c. Code Generation — AI generates executable code mapped to cloud services  
d. Testing — AI generates and executes functional, security, and performance tests  
e. Developers validate and approve at each step  

#### Operations Phase

AI analyzes telemetry (metrics, logs, traces), detects anomalies, integrates with incident runbooks, and proposes actionable recommendations. Developers validate and approve mitigations.

---

### The Workflow

Given a business intent, AI-DLC begins by generating a **Level 1 Plan**. Each step is then decomposed into finer-grained executable sub-tasks. All artifacts are persisted as "context memory" and linked for backward/forward traceability. AI performs strategic planning, task decomposition, and generation; humans provide oversight and validation.

---

## IV. Key Terminology Mapping

| AI-DLC | Traditional Scrum | Notes |
|--------|------------------|-------|
| Intent | Epic / Initiative | High-level purpose |
| Unit | Epic / Subdomain | Cohesive, deployable block |
| Story | User Story | With AC, same format |
| Bolt | Sprint | Hours/days, not weeks |
| Mob Elaboration | Sprint Planning + Refinement | AI-led, human-validated |
| Mob Construction | Development Sprint | AI executes, human approves |

---

## V. Flavors

- **DDD flavor** — primary flavor described in this paper
- **BDD flavor** — planned
- **TDD flavor** — planned

---

*Source: AI-DLC White Paper by Raja SP, AWS. Released at Bangalore Summit. Published on [AWS GitHub](https://github.com/awslabs/aidlc-workflows).*
