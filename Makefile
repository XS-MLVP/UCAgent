
all: clean test

init:
	pip3 install -r requirements.txt

dut:
	rm output -rf
	mkdir -p output
	cp -r examples output/

init_adder:
	rm output/examples/Adder -rf
	rm output/examples/DualPort -rf
	@if [ ! -d output/Adder ]; then \
        picker export examples/Adder/adder.v --rw 1 --tdir output/ -c -w add.fst; \
    fi
	cp examples/Adder/*.md output/Adder/
	cp doc/* output/ -r

test_adder: init_adder
	python3 verify.py output/ Adder --config config.yaml -s -hm --tui -l

mcp_adder: init_adder
	python3 verify.py output/ Adder --config config.yaml -s -hm --tui --mcp-server-no-file-tools --no-embed-tools

clean:
	rm -rf output

clean_test:
	rm -rf output/unity_test

continue:
	python3 verify.py output/ ${DUT} --config config.yaml ${ARGS}
