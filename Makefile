
all: clean test

init:
	pip3 install -r requirements.txt

dut:
	rm output -rf
	mkdir -p output

test_adder:
	@if [ ! -d output/Adder ]; then \
        picker export examples/Adder/adder.v --rw 1 --tdir output/; \
    fi
	cp examples/Adder/*.md output/Adder/
	cp doc/* output/ -r
	python3 verify.py output/ Adder --config config.yaml

clean:
	rm -rf output
