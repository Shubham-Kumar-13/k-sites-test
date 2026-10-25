#!/bin/bash

# K-Sites Web Application Startup Script
# Suite for Knock-out/down Studies

echo "============================================================"
echo "  K-Sites - Suite for Knock-out/down Studies"
echo "  Safe Gene Selection for Knockout Studies"
echo "============================================================"

# Check if running from correct directory
if [ ! -f "app.py" ]; then
    echo "Error: Please run this script from the webapp directory"
    exit 1
fi

# Set default NCBI email if not set
if [ -z "$K_SITES_NCBI_EMAIL" ]; then
    export K_SITES_NCBI_EMAIL="user@example.com"
    echo "Warning: K_SITES_NCBI_EMAIL not set, using default: $K_SITES_NCBI_EMAIL"
fi

echo ""
echo "Configuration:"
echo "  NCBI Email: $K_SITES_NCBI_EMAIL"
echo "  Mail Server: ${MAIL_SERVER:-Not configured (email disabled)}"


echo ""

# Check if K-Sites is installed
python -c "import k_sites" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Error: K-Sites package not found!"
    echo "Please install it first: cd .. && pip install -e ."
    exit 1
fi

echo "✓ K-Sites package found"

# Create results directory
mkdir -p results

# Check for optional dependencies
python -c "import flask" 2>/dev/null
if [ $? -ne 0 ]; then
    echo ""
    echo "Installing webapp dependencies..."
    pip install -r requirements.txt
fi

echo "✓ Dependencies OK"
echo ""

# Print environment setup instructions if email not configured
if [ -z "$MAIL_USERNAME" ]; then
    echo "============================================================"
    echo "  Email Notifications (Optional)"
    echo "============================================================"
    echo "To enable email notifications, set these environment variables:"
    echo ""
    echo "  export MAIL_USERNAME='your-email@gmail.com'"
    echo "  export MAIL_PASSWORD='your-app-password'"
    echo "  export MAIL_SERVER='smtp.gmail.com'"
    echo "  export MAIL_PORT=587"
    echo ""
    echo "For Gmail, use an App Password:"
    echo "  https://support.google.com/accounts/answer/185833"
    echo ""
fi

echo "============================================================"
echo "  Starting K-Sites Web Server"
echo "============================================================"
echo "  Local URL: http://localhost:5000"
echo "  Network:   http://0.0.0.0:5000"
echo "  Help Docs: http://localhost:5000/help"
echo "============================================================"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run the Flask application
python app.py "$@"
