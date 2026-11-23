from pathlib import Path
p=Path('samples/CMakeLists.txt')
s=p.read_text(encoding='utf-8')
old='''        materials/aiDetailNormal.mat
'''
new=old+'''        materials/aiParallax.mat
'''
assert old in s
s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('CMake material added')
