#!/bin/bash
#
# SENA Project - Full Setup Script
# =================================
# This script sets up PostgreSQL, Python environment, and all dependencies
# for running the SENA RAG application on a new system.
#
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
#
# Or run specific sections:
#   ./scripts/setup.sh postgres    # Only PostgreSQL setup
#   ./scripts/setup.sh python      # Only Python environment setup
#   ./scripts/setup.sh deps        # Only install dependencies
#   ./scripts/setup.sh verify      # Only verify setup
#

set -e

# ============================================================================
# CONFIGURATION - Modify these if needed
# ============================================================================

DB_NAME="${SENA_DB_NAME:-sena}"
DB_USER="${SENA_DB_USER:-postgres}"
DB_PASSWORD="${SENA_DB_PASSWORD:-postgres}"
DB_HOST="${SENA_DB_HOST:-localhost}"
DB_PORT="${SENA_DB_PORT:-5432}"
VENV_DIR="${SENA_VENV_DIR:-.venv}"
PYTHON_CMD="${SENA_PYTHON:-python3}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is not installed. Please install it first."
        return 1
    fi
    return 0
}

# ============================================================================
# POSTGRESQL SETUP
# ============================================================================

setup_postgresql() {
    log_info "Starting PostgreSQL setup..."

    # Check if PostgreSQL is installed
    if ! check_command psql; then
        log_error "PostgreSQL client (psql) not found."
        log_info "Install PostgreSQL with:"
        echo "  Ubuntu/Debian: sudo apt install postgresql postgresql-contrib"
        echo "  RHEL/CentOS:   sudo yum install postgresql-server postgresql-contrib"
        echo "  Fedora:        sudo dnf install postgresql-server postgresql-contrib"
        return 1
    fi

    # Check if PostgreSQL service is running
    if ! sudo -u postgres psql -c "SELECT 1;" &> /dev/null; then
        log_warn "PostgreSQL service may not be running. Attempting to start..."
        if command -v systemctl &> /dev/null; then
            sudo systemctl start postgresql
            sudo systemctl enable postgresql
        else
            sudo service postgresql start
        fi
    fi

    log_info "Setting PostgreSQL password for user '${DB_USER}'..."
    sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" 2>/dev/null || \
        log_warn "Could not alter user password (user may not exist or already configured)"

    log_info "Creating database '${DB_NAME}'..."
    sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME};" 2>/dev/null || \
        log_info "Database '${DB_NAME}' already exists"

    log_info "Granting privileges..."
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" 2>/dev/null || true

    # Install pgvector extension if available
    log_info "Checking for pgvector extension..."
    if sudo -u postgres psql -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null; then
        log_success "pgvector extension enabled"
    else
        log_warn "pgvector extension not available. Vector search may not work."
        log_info "Install pgvector with: sudo apt install postgresql-16-pgvector (or your version)"
    fi

    # Configure pg_hba.conf for local password auth if needed
    log_info "Verifying connection..."
    if PGPASSWORD="${DB_PASSWORD}" psql -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -d "${DB_NAME}" -c "SELECT 'Connection successful!';" 2>/dev/null; then
        log_success "PostgreSQL connection verified!"
    else
        log_warn "Could not verify connection. You may need to configure pg_hba.conf"
        log_info "Edit /etc/postgresql/*/main/pg_hba.conf and change 'peer' to 'md5' for local connections"
        log_info "Then run: sudo systemctl reload postgresql"
    fi

    log_success "PostgreSQL setup complete!"
}

# ============================================================================
# PYTHON ENVIRONMENT SETUP
# ============================================================================

setup_python() {
    log_info "Starting Python environment setup..."

    # Check Python version
    if ! check_command "${PYTHON_CMD}"; then
        log_error "Python not found. Please install Python 3.10 or later."
        return 1
    fi

    PYTHON_VERSION=$("${PYTHON_CMD}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Found Python ${PYTHON_VERSION}"

    # Check minimum version
    if [[ $(echo "${PYTHON_VERSION} < 3.10" | bc -l 2>/dev/null || echo "0") == "1" ]]; then
        log_warn "Python 3.10+ is recommended. You have ${PYTHON_VERSION}"
    fi

    # Create virtual environment
    if [[ -d "${VENV_DIR}" ]]; then
        log_info "Virtual environment '${VENV_DIR}' already exists"
    else
        log_info "Creating virtual environment '${VENV_DIR}'..."
        "${PYTHON_CMD}" -m venv "${VENV_DIR}"
        log_success "Virtual environment created"
    fi

    # Activate and upgrade pip
    log_info "Upgrading pip..."
    "${VENV_DIR}/bin/pip" install --upgrade pip wheel setuptools

    log_success "Python environment setup complete!"
}

# ============================================================================
# DEPENDENCIES INSTALLATION
# ============================================================================

install_dependencies() {
    log_info "Installing Python dependencies..."

    if [[ ! -d "${VENV_DIR}" ]]; then
        log_error "Virtual environment not found. Run './scripts/setup.sh python' first."
        return 1
    fi

    # Install from requirements.txt if it exists
    if [[ -f "requirements.txt" ]]; then
        log_info "Installing from requirements.txt..."
        "${VENV_DIR}/bin/pip" install -r requirements.txt
    else
        log_warn "requirements.txt not found. Installing core dependencies..."
        "${VENV_DIR}/bin/pip" install \
            nicegui \
            pydantic \
            paramiko \
            psycopg[binary] \
            requests \
            langgraph
    fi

    log_success "Dependencies installed!"
}

# ============================================================================
# CREATE .env FILE
# ============================================================================

create_env_file() {
    log_info "Creating .env file..."

    if [[ -f ".env" ]]; then
        log_warn ".env file already exists. Backing up to .env.backup"
        cp .env .env.backup
    fi

    cat > .env << EOF
# SENA Configuration
# ==================
# Copy this file or source it before running the application

# PostgreSQL Database
export PG_DSN="postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

# Ollama LLM Settings
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_CHAT_MODEL="qwen2.5:7b-instruct"
export OLLAMA_CHAT_SMALL_MODEL="nemotron-mini:4b"
export OLLAMA_EMBED_MODEL="nomic-embed-text"

# RAG Settings
export RAG_DEBUG="0"
export LIVE_SUMMARY_ENABLED="true"
export LIVE_OUTPUT_MODE="summary"
export CHAT_MAX_TOKENS="1024"

# SSH Config
export SENA_SSH_CONFIG="configs/ssh.json"
EOF

    chmod 600 .env
    log_success ".env file created! Source it with: source .env"
}

# ============================================================================
# DATA PREPARATION & INDEXING
# ============================================================================

prepare_data() {
    log_info "Preparing data (converting raw files to JSONL)..."

    if [[ ! -d "${VENV_DIR}" ]]; then
        log_error "Virtual environment not found. Run './scripts/setup.sh python' first."
        return 1
    fi

    # Check if raw data exists
    if [[ ! -d "data" ]]; then
        log_warn "No 'data' directory found. Creating structure..."
        mkdir -p data/raw/test_cases
        mkdir -p data/raw/system_logs
        mkdir -p data/processed
        log_info "Created data directory structure. Add your raw data files to data/raw/"
        return 0
    fi

    # Run the prepare_data script
    if [[ -f "src/ingest/prepare_data.py" ]]; then
        log_info "Running data preparation..."
        "${VENV_DIR}/bin/python" -m src.ingest.prepare_data --input-dir data --output-dir data/processed
        log_success "Data preparation complete!"
    else
        log_warn "src/ingest/prepare_data.py not found. Skipping preparation."
    fi
}

index_database() {
    log_info "Indexing data into PostgreSQL..."

    if [[ ! -d "${VENV_DIR}" ]]; then
        log_error "Virtual environment not found. Run './scripts/setup.sh python' first."
        return 1
    fi

    # Check if processed data exists
    PROCESSED_DIR="${1:-data/processed}"
    
    if [[ ! -f "${PROCESSED_DIR}/test_cases.jsonl" ]] && [[ ! -f "${PROCESSED_DIR}/system_logs.jsonl" ]]; then
        log_warn "No processed JSONL files found in ${PROCESSED_DIR}"
        log_info "Run './scripts/setup.sh prepare' first to generate JSONL files"
        return 1
    fi

    # Source environment if .env exists
    if [[ -f ".env" ]]; then
        source .env
    fi

    OLLAMA_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

    # Check if Ollama is running (needed for embeddings)
    log_info "Checking Ollama for embeddings at ${OLLAMA_URL}..."
    if ! curl -s "${OLLAMA_URL}/api/version" &>/dev/null; then
        log_warn "Ollama is not running. Starting Ollama..."
        if command -v ollama &> /dev/null; then
            ollama serve &>/dev/null &
            sleep 3
        else
            log_error "Ollama not found. Please install and start Ollama first."
            log_info "Install: curl -fsSL https://ollama.com/install.sh | sh"
            log_info "Then run: ollama serve"
            return 1
        fi
    fi

    # Ensure embedding model is available
    log_info "Ensuring embedding model is available..."
    EMBED_MODEL="${OLLAMA_EMBED_MODEL:-nomic-embed-text}"
    if ! ollama list 2>/dev/null | grep -q "${EMBED_MODEL}"; then
        log_info "Pulling embedding model ${EMBED_MODEL}..."
        ollama pull "${EMBED_MODEL}"
    fi

    # Run the indexing script
    log_info "Running database indexing (this may take a while)..."
    "${VENV_DIR}/bin/python" index_data.py --processed-dir "${PROCESSED_DIR}" --progress-every 50

    log_success "Database indexing complete!"
}

update_database() {
    log_info "============================================"
    log_info "Updating Database (Prepare + Index)"
    log_info "============================================"
    echo ""

    prepare_data
    echo ""
    index_database "$@"
}

verify_database() {
    log_info "Verifying database contents..."

    if [[ ! -d "${VENV_DIR}" ]]; then
        log_error "Virtual environment not found."
        return 1
    fi

    # Source environment if .env exists
    if [[ -f ".env" ]]; then
        source .env
    fi

    "${VENV_DIR}/bin/python" << 'PYEOF'
import sys
try:
    from src.db.postgres import get_connection
    from src.config import load_config
    
    cfg = load_config()
    conn = get_connection(cfg.pg_dsn)
    cur = conn.cursor()
    
    # Check test_cases
    cur.execute("SELECT COUNT(*) FROM test_cases")
    test_count = cur.fetchone()[0]
    
    # Check system_logs
    cur.execute("SELECT COUNT(*) FROM system_logs")
    system_count = cur.fetchone()[0]
    
    # Check for embeddings
    cur.execute("SELECT COUNT(*) FROM test_cases WHERE embedding IS NOT NULL")
    test_embed_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM system_logs WHERE embedding IS NOT NULL")
    system_embed_count = cur.fetchone()[0]
    
    conn.close()
    
    print(f"\n{'='*50}")
    print("Database Contents:")
    print(f"{'='*50}")
    print(f"  Test Cases:    {test_count:>6} records ({test_embed_count} with embeddings)")
    print(f"  System Logs:   {system_count:>6} records ({system_embed_count} with embeddings)")
    print(f"{'='*50}")
    
    if test_count == 0 and system_count == 0:
        print("\n[WARN] Database is empty. Run: ./scripts/setup.sh update")
        sys.exit(1)
    else:
        print("\n[OK] Database has data!")
        
except Exception as e:
    print(f"[ERROR] Database verification failed: {e}")
    sys.exit(1)
PYEOF
}

# ============================================================================
# VERIFY SETUP
# ============================================================================

verify_setup() {
    log_info "Verifying setup..."
    
    ERRORS=0

    # Check PostgreSQL
    log_info "Checking PostgreSQL connection..."
    if PGPASSWORD="${DB_PASSWORD}" psql -U "${DB_USER}" -h "${DB_HOST}" -p "${DB_PORT}" -d "${DB_NAME}" -c "SELECT 1;" &>/dev/null; then
        log_success "PostgreSQL: OK"
    else
        log_error "PostgreSQL: FAILED"
        ((ERRORS++))
    fi

    # Check virtual environment
    log_info "Checking Python environment..."
    if [[ -f "${VENV_DIR}/bin/python" ]]; then
        log_success "Virtual environment: OK"
    else
        log_error "Virtual environment: NOT FOUND"
        ((ERRORS++))
    fi

    # Check key dependencies
    log_info "Checking key dependencies..."
    for pkg in nicegui pydantic paramiko psycopg langgraph; do
        if "${VENV_DIR}/bin/pip" show "${pkg}" &>/dev/null; then
            log_success "  ${pkg}: installed"
        else
            log_warn "  ${pkg}: NOT INSTALLED"
        fi
    done

    # Check Ollama
    log_info "Checking Ollama..."
    if curl -s "http://127.0.0.1:11434/api/version" &>/dev/null; then
        log_success "Ollama: OK (running)"
    else
        log_warn "Ollama: NOT RUNNING (start with: ollama serve)"
    fi

    # Check SSH config
    log_info "Checking SSH config..."
    if [[ -f "configs/ssh.json" ]]; then
        log_success "SSH config: OK"
    else
        log_warn "SSH config: NOT FOUND (create configs/ssh.json)"
    fi

    # Check database contents
    log_info "Checking database contents..."
    verify_database 2>/dev/null || log_warn "Database may be empty"

    # Summary
    echo ""
    if [[ ${ERRORS} -eq 0 ]]; then
        log_success "============================================"
        log_success "All checks passed! You can run the app with:"
        log_success "  source .env && ${VENV_DIR}/bin/python ui_nicegui/sena.py"
        log_success "============================================"
    else
        log_error "============================================"
        log_error "${ERRORS} check(s) failed. Please fix the issues above."
        log_error "============================================"
        return 1
    fi
}

# ============================================================================
# FULL SETUP
# ============================================================================

full_setup() {
    log_info "============================================"
    log_info "SENA Project - Full Setup"
    log_info "============================================"
    echo ""

    setup_postgresql
    echo ""
    setup_python
    echo ""
    install_dependencies
    echo ""
    create_env_file
    echo ""
    
    # Ask about data indexing
    echo ""
    log_info "Do you want to index data into the database now? (y/n)"
    read -r answer
    if [[ "${answer}" =~ ^[Yy] ]]; then
        update_database
    else
        log_info "Skipping data indexing. Run './scripts/setup.sh update' later."
    fi
    
    echo ""
    verify_setup
}

# ============================================================================
# MAIN
# ============================================================================

cd "$(dirname "$0")/.." || exit 1

case "${1:-all}" in
    postgres|pg|db)
        setup_postgresql
        ;;
    python|py|venv)
        setup_python
        ;;
    deps|dependencies|install)
        install_dependencies
        ;;
    env|config)
        create_env_file
        ;;
    prepare|prep)
        prepare_data
        ;;
    index)
        index_database "${2:-data/processed}"
        ;;
    update|refresh|data)
        update_database "${2:-data/processed}"
        ;;
    verify-db|check-db)
        verify_database
        ;;
    verify|check|test)
        verify_setup
        ;;
    all|full|"")
        full_setup
        ;;
    *)
        echo "Usage: $0 [command] [options]"
        echo ""
        echo "Setup Commands:"
        echo "  postgres     - Set up PostgreSQL database"
        echo "  python       - Create Python virtual environment"
        echo "  deps         - Install Python dependencies"
        echo "  env          - Create .env configuration file"
        echo "  all          - Run full setup (default)"
        echo ""
        echo "Data Commands:"
        echo "  prepare      - Convert raw data to JSONL format"
        echo "  index [dir]  - Index JSONL data into PostgreSQL"
        echo "  update [dir] - Prepare + Index (full data refresh)"
        echo ""
        echo "Verification:"
        echo "  verify       - Verify complete setup"
        echo "  verify-db    - Check database contents only"
        echo ""
        echo "Examples:"
        echo "  $0                           # Full setup"
        echo "  $0 postgres                  # Only PostgreSQL"
        echo "  $0 update                    # Full data refresh"
        echo "  $0 index data/processed      # Index from custom dir"
        exit 1
        ;;
esac
