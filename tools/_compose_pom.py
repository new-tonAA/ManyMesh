from PIL import Image
names=['out/pom-ref2.png','out/pom-detail.png','out/pom-detail-p1.png','out/pom-detail-p2.png']
ims=[Image.open(n).convert('RGB') for n in names]
w,h=ims[0].size
# centre crop around the face/eyes
box=(w//2-260,h//2-220,w//2+260,h//2+220)
crops=[im.crop(box) for im in ims]
cw,ch=crops[0].size
out=Image.new('RGB',(cw*len(crops),ch))
for i,c in enumerate(crops): out.paste(c,(cw*i,0))
out.save('out/pom-crops.png')
print(out.size)
