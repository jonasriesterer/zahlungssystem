#!/bin/bash
# Generate gRPC Python code from protobuf files

set -e

echo "Generating gRPC Python code from protobuf files..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Generate gRPC code for gRPC Service
echo "  → Generating invoice service for gRPC Service..."
GEN_DIR_GRPC="$SCRIPT_DIR/grpc_service/generated"
mkdir -p "$GEN_DIR_GRPC"
touch "$GEN_DIR_GRPC/__init__.py"

# Use uv to run Python modules
run_python_module() {
  uv run python -m "$@"
}

# Generate invoice service for gRPC
run_python_module grpc_tools.protoc \
  -I./grpc_service/proto \
  --python_out="$GEN_DIR_GRPC" \
  --grpc_python_out="$GEN_DIR_GRPC" \
  ./grpc_service/proto/invoice.proto

# Ensure generated grpc stub resolves module from the same package (gRPC Service)
sed -i 's/^import invoice_pb2 as/from . import invoice_pb2 as/' "$GEN_DIR_GRPC/invoice_pb2_grpc.py"

# Generate gRPC code for Payment Service
echo "  → Generating payment service and invoice client stubs for Payment Service..."
GEN_DIR_PAYMENT="$SCRIPT_DIR/payment_service/generated"
mkdir -p "$GEN_DIR_PAYMENT"
touch "$GEN_DIR_PAYMENT/__init__.py"

# Generate payment messages
run_python_module grpc_tools.protoc \
  -I./payment_service/proto \
  --python_out="$GEN_DIR_PAYMENT" \
  --grpc_python_out="$GEN_DIR_PAYMENT" \
  ./payment_service/proto/payment.proto

# Generate invoice client stubs for payment service (to call gRPC service)
run_python_module grpc_tools.protoc \
  -I./grpc_service/proto \
  --python_out="$GEN_DIR_PAYMENT" \
  --grpc_python_out="$GEN_DIR_PAYMENT" \
  ./grpc_service/proto/invoice.proto

# Ensure generated grpc stub resolves module from the same package (Payment Service)
sed -i 's/^import invoice_pb2 as/from . import invoice_pb2 as/' "$GEN_DIR_PAYMENT/invoice_pb2_grpc.py"

echo "✅ gRPC code generation completed!"
echo "Generated files:"
echo "  gRPC Service:"
echo "    - grpc_service/generated/invoice_pb2.py"
echo "    - grpc_service/generated/invoice_pb2_grpc.py"
echo "  Payment Service:"
echo "    - payment_service/generated/payment_pb2.py"
echo "    - payment_service/generated/invoice_pb2.py (client stubs for calling gRPC service)"
echo "    - payment_service/generated/invoice_pb2_grpc.py"
