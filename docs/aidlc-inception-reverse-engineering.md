# Reverse Engineering
*Source: [awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows) — `aidlc-rules/aws-aidlc-rule-details/inception/reverse-engineering.md`*

---

**Purpose**: Analyze existing codebase and generate comprehensive design artifacts

**Execute when**: Brownfield project detected (existing code found in workspace)

**Skip when**: Greenfield project (no existing code)

**Rerun behavior**: Controlled by workspace-detection.md. If existing artifacts are current, they are loaded and reverse engineering is skipped. If artifacts are stale or user explicitly requests rerun, reverse engineering executes again.

---

## Step 1: Multi-Package Discovery

### 1.1 Scan Workspace
- All packages (not just mentioned ones)
- Package relationships via config files
- Package types: Application, CDK/Infrastructure, Models, Clients, Tests

### 1.2 Understand the Business Context
- The core business that the system is implementing overall
- The business overview of every package
- List of Business Transactions implemented in the system

### 1.3 Infrastructure Discovery
- CDK packages (package.json with CDK dependencies)
- Terraform (.tf files)
- CloudFormation (.yaml/.json templates)
- Deployment scripts

### 1.4 Build System Discovery
- Build systems: Brazil, Maven, Gradle, npm
- Config files for build-system declarations
- Build dependencies between packages

### 1.5 Service Architecture Discovery
- Lambda functions (handlers, triggers)
- Container services (Docker/ECS configs)
- API definitions (Smithy models, OpenAPI specs)
- Data stores (DynamoDB, S3, etc.)

### 1.6 Code Quality Analysis
- Programming languages and frameworks
- Test coverage indicators
- Linting configurations
- CI/CD pipelines

---

## Step 2: Generate Business Overview Documentation

Create `aidlc-docs/inception/reverse-engineering/business-overview.md`:

```markdown
# Business Overview

## Business Context Diagram
[Mermaid diagram showing the Business Context]

## Business Description
- **Business Description**: [Overall Business description]
- **Business Transactions**: [List of Business Transactions and their descriptions]
- **Business Dictionary**: [Business dictionary terms and their meaning]

## Component Level Business Descriptions
### [Package/Component Name]
- **Purpose**: [What it does from the business perspective]
- **Responsibilities**: [Key responsibilities]
```

## Step 3: Generate Architecture Documentation

Create `aidlc-docs/inception/reverse-engineering/architecture.md`:

```markdown
# System Architecture

## Architecture Diagram
[Mermaid diagram showing all packages, services, data stores, relationships]

## Component Descriptions
### [Package/Component Name]
- **Purpose**: [What it does]
- **Responsibilities**: [Key responsibilities]
- **Dependencies**: [What it depends on]
- **Type**: [Application/Infrastructure/Model/Client/Test]

## Data Flow
[Mermaid sequence diagram of key workflows]

## Integration Points
- **External APIs**: [List with purposes]
- **Databases**: [List with purposes]
- **Third-party Services**: [List with purposes]
```

## Step 4: Generate Code Structure Documentation

Create `aidlc-docs/inception/reverse-engineering/code-structure.md`:

```markdown
# Code Structure

## Key Classes/Modules

### Existing Files Inventory
[List all source files with their purposes — these are candidates for modification in brownfield projects]

**Format**:
- `[path/to/file]` - [Purpose/responsibility]

## Design Patterns
### [Pattern Name]
- **Location**: [Where used]
- **Purpose**: [Why used]
```

## Step 5: Generate API Documentation

Create `aidlc-docs/inception/reverse-engineering/api-documentation.md`:

```markdown
# API Documentation

## REST APIs
### [Endpoint Name]
- **Method**: [GET/POST/PUT/DELETE]
- **Path**: [/api/path]
- **Request**: [Request format]
- **Response**: [Response format]

## Data Models
### [Model Name]
- **Fields**: [Field descriptions]
- **Relationships**: [Related models]
```

## Step 6: Generate Component Inventory

Create `aidlc-docs/inception/reverse-engineering/component-inventory.md`

## Step 7: Generate Technology Stack Documentation

Create `aidlc-docs/inception/reverse-engineering/technology-stack.md`

## Step 8: Generate Dependencies Documentation

Create `aidlc-docs/inception/reverse-engineering/dependencies.md`

## Step 9: Generate Code Quality Assessment

Create `aidlc-docs/inception/reverse-engineering/code-quality-assessment.md`:

```markdown
# Code Quality Assessment

## Test Coverage
- **Overall**: [Percentage or Good/Fair/Poor/None]

## Technical Debt
- [Issue description and location]

## Patterns and Anti-patterns
- **Good Patterns**: [List]
- **Anti-patterns**: [List with locations]
```

## Step 10: Create Timestamp File

Create `aidlc-docs/inception/reverse-engineering/reverse-engineering-timestamp.md` with ISO timestamp.

## Step 11: Update State Tracking

Update `aidlc-docs/aidlc-state.md`:
```markdown
## Reverse Engineering Status
- [x] Reverse Engineering - Completed on [timestamp]
- **Artifacts Location**: aidlc-docs/inception/reverse-engineering/
```

## Step 12: Present Completion Message

```markdown
# 🔍 Reverse Engineering Complete

> **📋 REVIEW REQUIRED:**
> Please examine the reverse engineering artifacts at: `aidlc-docs/inception/reverse-engineering/`

> **🚀 WHAT'S NEXT?**
> 🔧 **Request Changes** - Ask for modifications if required
> ✅ **Approve & Continue** - Approve analysis and proceed to **Requirements Analysis**
```

## Step 13: Wait for User Approval
- **MANDATORY**: Do not proceed until user explicitly approves
- **MANDATORY**: Log user's response in audit.md

---

## Hello Scrum Context

Hello Scrum is a brownfield application. Reverse engineering would analyze: `server.py`, `agent.py`, `board.html`, `index.html`, `sdlc_pipeline.json` — producing a component inventory covering the Flask server, Claude agent pipeline, and HTML/JS frontend.
