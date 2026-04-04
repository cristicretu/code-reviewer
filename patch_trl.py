import glob
files = glob.glob('/usr/local/lib/python3.11/dist-packages/trl/trainer/sft_trainer.py')
if not files:
    files = glob.glob('/usr/lib/python*/dist-packages/trl/trainer/sft_trainer.py')
for p in files:
    f = open(p)
    s = f.read()
    f.close()
    s = s.replace('if args.eos_token is not None:', 'if False:')
    s = s.replace('if args.pad_token is not None:', 'if False:')
    f = open(p, 'w')
    f.write(s)
    f.close()
    print('Patched: ' + p)
