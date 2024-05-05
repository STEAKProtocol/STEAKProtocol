# Makefile for compiling LaTeX documents


# Main target
all: contracts

# Compile contracts
contracts: steak_protocol
	poetry install || echo "Running poetry failed, did you make sure to install it?"
	poetry run python3 steak_protocol/build.py



# Clean auxiliary files
clean:

# Clean all files including PDF
distclean: clean
	rm -r build

# Phony targets
.PHONY: all clean distclean
