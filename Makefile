
all: clean test

init:
	pip3 install -r requirements.txt

dut:
	rm output -rf
	mkdir -p output/ALU
	cp -r examples/ALU/alu output/ALU/
	cp -r doc/* output/ALU/

test:
	python3 verify.py output/ALU  alu --config config.yaml

